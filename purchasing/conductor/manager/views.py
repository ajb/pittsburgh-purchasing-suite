# -*- coding: utf-8 -*-

import urllib2
import json

from flask import (
    render_template, flash, redirect, current_app,
    url_for, abort, request, jsonify, session
)
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from purchasing.decorators import requires_roles
from purchasing.database import db, get_or_create
from purchasing.notifications import Notification

from purchasing.data.stages import Stage, get_contract_stages
from purchasing.data.flows import Flow, switch_flow
from purchasing.data.contracts import ContractBase, ContractProperty, ContractType
from purchasing.data.companies import Company, CompanyContact
from purchasing.data.contract_stages import ContractStage, ContractStageActionItem

from purchasing.users.models import User, Role, Department
from purchasing.conductor.forms import (
    EditContractForm, PostOpportunityForm,
    SendUpdateForm, NoteForm, ContractMetadataForm, CompanyListForm,
    CompanyContactListForm, NewContractForm
)

from purchasing.conductor.util import (
    handle_form, ContractMetadataObj, build_subscribers,
    json_serial, parse_companies, UpdateFormObj, assign_a_contract
)

from purchasing.conductor.manager import blueprint

@blueprint.route('/')
@requires_roles('conductor', 'admin', 'superadmin')
def index():
    in_progress = db.session.query(
        db.distinct(ContractBase.id).label('id'),
        ContractBase.description, Flow.flow_name,
        Stage.name.label('stage_name'), ContractStage.entered,
        User.first_name, User.email,
        Department.name.label('department')
    ).outerjoin(Department).join(
        ContractStage, db.and_(
            ContractStage.stage_id == ContractBase.current_stage_id,
            ContractStage.contract_id == ContractBase.id,
            ContractStage.flow_id == ContractBase.flow_id
        )
    ).join(
        Stage, Stage.id == ContractBase.current_stage_id
    ).join(
        Flow, Flow.id == ContractBase.flow_id
    ).join(User, User.id == ContractBase.assigned_to).filter(
        ContractStage.entered != None,
        ContractBase.assigned_to != None,
        ContractStage.flow_id == ContractBase.flow_id,
        ContractBase.is_visible == False,
        ContractBase.is_archived == False
    ).all()

    all_contracts = db.session.query(
        ContractBase.id, ContractBase.description,
        ContractBase.financial_id, ContractBase.expiration_date,
        ContractProperty.value.label('spec_number'),
        ContractBase.contract_href, ContractBase.department,
        User.first_name, User.email
    ).join(ContractType).outerjoin(
        User, User.id == ContractBase.assigned_to
    ).outerjoin(
        Department, Department.id == ContractBase.department_id
    ).outerjoin(
        ContractProperty, ContractProperty.contract_id == ContractBase.id
    ).filter(
        db.func.lower(ContractType.name).in_(['county', 'a-bid', 'b-bid']),
        db.func.lower(ContractProperty.key) == 'spec number',
        ContractBase.children == None,
        ContractBase.is_visible == True
    ).order_by(ContractBase.expiration_date).all()

    conductors = User.query.join(Role, User.role_id == Role.id).filter(
        Role.name == 'conductor',
        User.email != current_user.email
    ).all()

    current_app.logger.info('CONDUCTOR INDEX - Conductor index page view')

    return render_template(
        'conductor/index.html',
        in_progress=in_progress, _all=all_contracts,
        current_user=current_user,
        conductors=[current_user] + conductors,
        path='{path}?{query}'.format(
            path=request.path, query=request.query_string
        )
    )

@blueprint.route('/contract/<int:contract_id>', methods=['GET', 'POST'])
@blueprint.route('/contract/<int:contract_id>/stage/<int:stage_id>', methods=['GET', 'POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def detail(contract_id, stage_id=-1):
    '''View to control an individual stage update process
    '''
    contract = ContractBase.query.get(contract_id)
    if not contract:
        abort(404)

    if contract.completed_last_stage():
        return redirect(url_for('conductor.edit', contract_id=contract.id))

    if stage_id == -1:
        # redirect to the current stage page
        contract_stage = contract.get_current_stage()

        if contract_stage:
            return redirect(url_for(
                'conductor.detail', contract_id=contract_id, stage_id=contract_stage.id
            ))
        current_app.logger.warning('Could not find stages for this contract, aborting!')
        abort(500)

    stages = get_contract_stages(contract)

    try:
        active_stage = [i for i in stages if i.id == stage_id][0]
        current_stage = [i for i in stages if i.entered and not i.exited][0]
        if active_stage.entered is None:
            abort(404)
    except IndexError:
        abort(404)

    note_form = NoteForm()
    update_form = SendUpdateForm(obj=UpdateFormObj(current_stage))
    opportunity_form = PostOpportunityForm(
        obj=contract.opportunity if contract.opportunity else contract
    )
    metadata_form = ContractMetadataForm(obj=ContractMetadataObj(contract))

    forms = {
        'activity': note_form, 'update': update_form,
        'post': opportunity_form, 'update-metadata': metadata_form
    }

    active_tab = '#activity'

    submitted_form = request.args.get('form', None)

    if submitted_form:
        if handle_form(
            forms[submitted_form], submitted_form, stage_id,
            current_user, contract, active_stage
        ):
            return redirect(url_for(
                'conductor.detail', contract_id=contract_id, stage_id=stage_id
            ))
        else:
            active_tab = '#' + submitted_form

    actions = contract.build_complete_action_log()
    subscribers, total_subscribers = build_subscribers(contract)
    flows = Flow.query.filter(Flow.id != contract.flow_id).all()

    current_app.logger.info(
        'CONDUCTOR DETAIL VIEW - Detail view for contract {} (ID: {}), stage {}'.format(
            contract.description, contract.id, current_stage.name
        )
    )

    opportunity_form.display_cleanup()

    if len(stages) > 0:
        return render_template(
            'conductor/detail.html',
            stages=stages, actions=actions, active_tab=active_tab,
            note_form=note_form, update_form=update_form,
            opportunity_form=opportunity_form, metadata_form=metadata_form,
            contract=contract, current_user=current_user,
            active_stage=active_stage, current_stage=current_stage,
            flows=flows, subscribers=subscribers,
            total_subscribers=total_subscribers, categories=opportunity_form.get_categories(),
            subcategories=opportunity_form.get_subcategories()
        )
    abort(404)

@blueprint.route('/contract/<int:contract_id>/stage/<int:stage_id>/transition')
@requires_roles('conductor', 'admin', 'superadmin')
def transition(contract_id, stage_id):
    contract = ContractBase.query.get(contract_id)
    if not contract:
        abort(404)

    clicked = int(request.args.get('destination')) if \
        request.args.get('destination') else None

    try:
        actions = contract.transition(current_user, destination=clicked)
        for action in actions:
            db.session.add(action)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        pass
    except Exception:
        db.session.rollback()
        raise

    current_app.logger.info(
        'CONDUCTOR TRANSITION - Contract for {} (ID: {}) transition to {}'.format(
            contract.description, contract.id, contract.current_stage.name
        )
    )

    if contract.completed_last_stage():
        url = url_for('conductor.edit', contract_id=contract.id)
    else:
        url = url_for('conductor.detail', contract_id=contract.id)

    return redirect(url)

@blueprint.route('/contract/<int:contract_id>/stage/<int:stage_id>/extend')
@requires_roles('conductor', 'admin', 'superadmin')
def extend(contract_id, stage_id):
    contract = ContractBase.query.get(contract_id)
    if not contract:
        abort(404)

    extended_contract = contract.parent.extend(delete_children=False)
    current_app.logger.info(
        'CONDUCTOR EXTEND - Contract for {} (ID: {}) extended'.format(
            extended_contract.description, extended_contract.id
        )
    )
    db.session.commit()

    flash(
        'This contract has been extended. Please add the new expiration date below.',
        'alert-warning'
    )

    session['extend'] = True
    return redirect(url_for(
        'conductor.edit', contract_id=extended_contract.id
    ))


@blueprint.route('/contract/<int:contract_id>/stage/<int:stage_id>/flow-switch/<int:flow_id>')
@requires_roles('conductor', 'admin', 'superadmin')
def flow_switch(contract_id, stage_id, flow_id):
    contract = ContractBase.query.get(contract_id)
    if not contract:
        abort(404)

    new_contract_stage, contract = switch_flow(
        flow_id, contract_id, current_user
    )

    current_app.logger.info(
        'CONDUCTOR FLOW SWITCH - Contract for {} (ID: {}) switched to new flow {}'.format(
            contract.description, contract.id, contract.flow.flow_name
        )
    )
    return redirect(url_for(
        'conductor.detail', contract_id=contract_id, stage_id=new_contract_stage.id
    ))

@blueprint.route('/contract/<int:contract_id>/kill')
@requires_roles('conductor', 'admin', 'superadmin')
def kill_contract(contract_id):
    '''Allow a contract to die on the vine
    '''
    contract = ContractBase.query.get(contract_id)
    if contract:
        flash_description = contract.description
        contract.kill()
        db.session.commit()
        current_app.logger.info(
            'CONDUCTOR KILL - Contract for {} (ID: {}) killed'.format(
                flash_description, contract.id
            )
        )
        flash('Successfully removed {} from use!'.format(flash_description), 'alert-success')
        return redirect(url_for('conductor.index'))
    abort(404)

@blueprint.route(
    '/contract/<int:contract_id>/stage/<int:stage_id>/note/<int:note_id>/delete',
    methods=['GET', 'POST']
)
@requires_roles('conductor', 'admin', 'superadmin')
def delete_note(contract_id, stage_id, note_id):
    try:
        note = ContractStageActionItem.query.get(note_id)
        if note:
            current_app.logger.info('Conductor note delete')
            note.delete()
            flash('Note deleted successfully!', 'alert-success')
        else:
            flash("That note doesn't exist!", 'alert-warning')
    except Exception, e:
        current_app.logger.error('Conductor note delete error: {}'.format(str(e)))
        flash('Something went wrong: {}'.format(e.message), 'alert-danger')
    return redirect(url_for('conductor.detail', contract_id=contract_id))

@blueprint.route('/contract/new', methods=['GET', 'POST'])
@blueprint.route('/contract/<int:contract_id>/start', methods=['GET', 'POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def start_work(contract_id=-1):
    contract = ContractBase.query.get(contract_id)
    contract = contract if contract else ContractBase()
    form = NewContractForm(obj=contract)

    if form.validate_on_submit():
        if contract_id == -1:
            contract, _ = get_or_create(
                db.session, ContractBase, description=form.data.get('description'),
                department=form.data.get('department'), is_visible=False
            )
        else:
            contract = ContractBase.clone(contract)
            contract.description = form.data.get('description')
            contract.department = form.data.get('department')
            db.session.add(contract)
            db.session.commit()

        assigned = assign_a_contract(contract, form.data.get('flow'), form.data.get('assigned').id, clone=False)
        db.session.commit()

        if assigned:
            flash('Successfully assigned {} to {}!'.format(assigned.description, assigned.assigned.email), 'alert-success')
            return redirect(url_for('conductor.detail', contract_id=assigned.id))
        else:
            flash("That flow doesn't exist!", 'alert-danger')
    return render_template('conductor/new.html', form=form, contract_id=contract_id)

@blueprint.route('/contract/<int:contract_id>/edit/contract', methods=['GET', 'POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def edit(contract_id):
    '''Update information about a contract
    '''
    contract = ContractBase.query.get(contract_id)
    completed_last_stage = contract.completed_last_stage()

    # clear the contract/companies from our session
    session.pop('contract', None)
    session.pop('companies', None)

    extend = session.get('extend', None)

    if contract and completed_last_stage or extend:
        form = EditContractForm(obj=contract)
        if form.validate_on_submit():
            if not extend:
                session['contract'] = json.dumps(form.data, default=json_serial)
                return redirect(url_for('conductor.edit_company', contract_id=contract.id))
            else:
                # if there is no flow, that means that it is an extended contract
                # so we will save it and return back to the conductor home page
                contract.update_with_spec_number(form.data)
                current_app.logger.info('CONDUCTOR CONTRACT COMPLETE - contract metadata for "{}" updated'.format(
                    contract.description
                ))
                session.pop('extend')
                return redirect(url_for('conductor.index'))
        form.spec_number.data = contract.get_spec_number().value
        return render_template('conductor/edit/edit.html', form=form, contract=contract)
    elif not completed_last_stage:
        return redirect(url_for('conductor.detail', contract_id=contract.id))
    abort(404)

@blueprint.route('/contract/<int:contract_id>/edit/company', methods=['GET', 'POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def edit_company(contract_id):
    contract = ContractBase.query.get(contract_id)

    if contract and session.get('contract') is not None:
        form = CompanyListForm()
        if form.validate_on_submit():
            cleaned = parse_companies(form.data)
            session['companies'] = json.dumps(cleaned, default=json_serial)
            current_app.logger.info('CONDUCTOR CONTRACT COMPLETE - awarded companies for contract "{}" assigned'.format(
                contract.description
            ))
            return redirect(url_for('conductor.edit_company_contacts', contract_id=contract.id))
        return render_template('conductor/edit/edit_company.html', form=form, contract=contract)
    elif session.get('contract') is None:
        return redirect(url_for('conductor.edit', contract_id=contract_id))
    abort(404)

@blueprint.route('/contract/<int:contract_id>/edit/contacts', methods=['GET', 'POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def edit_company_contacts(contract_id):
    contract = ContractBase.query.get(contract_id)

    if contract and session.get('contract') is not None and session.get('companies') is not None:
        form = CompanyContactListForm()

        companies = json.loads(session['companies'])
        contract_data = json.loads(session['contract'])

        if form.validate_on_submit():
            main_contract = contract
            for ix, _company in enumerate(companies):
                # because multiple companies can have the same name, don't use
                # get_or_create because it can create multiples
                if _company.get('company_id') > 0:
                    company = Company.query.get(_company.get('company_id'))
                else:
                    company = Company.create(company_name=_company.get('company_name'))
                # contacts should be unique to companies, though
                for _contact in form.data.get('companies')[ix].get('contacts'):
                    _contact['company_id'] = company.id
                    contact, _ = get_or_create(db.session, CompanyContact, **_contact)

                contract_data['financial_id'] = _company['financial_id']
                if ix == 0:
                    contract.update_with_spec_number(contract_data, company=company)
                else:
                    contract = ContractBase.clone(contract, parent_id=contract.parent_id, strip=False)
                    contract.update_with_spec_number(contract_data, company=company)

                contract.is_visible = True
                contract.parent.is_archived = True
                if not contract.parent.description.endswith('[Archived]'):
                    contract.parent.description += ' [Archived]'

                db.session.commit()

            Notification(
                to_email=[i.email for i in contract.followers],
                from_email=current_app.config['CONDUCTOR_SENDER'],
                reply_to=current_user.email,
                subject='A contract you follow has been updated!',
                html_template='conductor/emails/new_contract.html',
                contract=main_contract
            ).send(multi=True)

            session.pop('contract')
            session.pop('companies')
            session['success'] = True

            current_app.logger.info('''
CONDUCTOR CONTRACT COMPLETE - company contacts for contract "{}" assigned. |New contract(s) successfully created'''.format(
                contract.description
            ))

            return redirect(url_for('conductor.success', contract_id=main_contract.id))

        if len(form.companies.entries) == 0:
            for company in companies:
                form.companies.append_entry()

        return render_template(
            'conductor/edit/edit_company_contacts.html', form=form, contract=contract,
            companies=companies
        )
    elif session.get('contract') is None:
        return redirect(url_for('conductor.edit', contract_id=contract_id))
    elif session.get('companies') is None:
        return redirect(url_for('conductor.edit_company', contract_id=contract_id))
    abort(404)

@blueprint.route('/contract/<int:contract_id>/edit/success', methods=['GET', 'POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def success(contract_id):
    if session.pop('success', None):
        contract = ContractBase.query.get(contract_id)
        return render_template('conductor/edit/success.html', contract=contract)
    return redirect(url_for('conductor.edit_company_contacts', contract_id=contract_id))

@blueprint.route('/contract/<int:contract_id>/edit/url-exists', methods=['POST'])
@requires_roles('conductor', 'admin', 'superadmin')
def url_exists(contract_id):
    '''Check to see if a url returns an actual page
    '''
    url = request.json.get('url', '')
    if url == '':
        return jsonify({'status': 404})

    req = urllib2.Request(url)
    request.get_method = lambda: 'HEAD'

    try:
        response = urllib2.urlopen(req)
        return jsonify({'status': response.getcode()})
    except urllib2.HTTPError, e:
        return jsonify({'status': e.getcode()})

@blueprint.route('/contract/<int:contract_id>/assign/<int:user_id>/flow/<int:flow_id>')
@requires_roles('conductor', 'admin', 'superadmin')
def assign(contract_id, flow_id, user_id):
    '''Assign & start work on a contract to an admin or a conductor
    '''
    contract = ContractBase.query.get(contract_id)
    flow = Flow.query.get(flow_id)

    assigned = assign_a_contract(contract, flow, user_id)
    if assigned:
        flash('Successfully assigned {} to {}!'.format(assigned.description, assigned.assigned.email), 'alert-success')
        return redirect(url_for('conductor.index'))
    else:
        flash("That flow doesn't exist!", 'alert-danger')
        return redirect(url_for('conductor.index'))
