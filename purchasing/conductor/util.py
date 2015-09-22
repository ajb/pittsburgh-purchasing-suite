# -*- coding: utf-8 -*-

import datetime
from collections import defaultdict

from sqlalchemy.exc import IntegrityError

from flask import request, current_app
from flask_login import current_user

from purchasing.database import db
from purchasing.notifications import Notification

from purchasing.data.contracts import ContractBase
from purchasing.data.contract_stages import ContractStageActionItem
from purchasing.data.flows import create_contract_stages
from purchasing.opportunities.models import Opportunity
from purchasing.users.models import User, Role, Department

from purchasing.opportunities.util import (
    build_opportunity, fix_form_categories
)

class ContractMetadataObj(object):
    def __init__(self, contract):
        self.expiration_date = contract.expiration_date
        self.financial_id = contract.financial_id
        self.spec_number = contract.get_spec_number().value
        self.department = contract.department

class OpportunityFormObj(object):
    def __init__(self, department, title, contact_email=None):
        self.department = department
        self.title = title
        self.contact_email = contact_email

class UpdateFormObj(object):
    def __init__(self, stage):
        self.body = stage.default_message if stage.default_message else ''

def json_serial(obj):
    if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date):
        return obj.isoformat()

def create_opp_form_obj(contract, contact_email=None):
    if contract.opportunity:
        obj = contract.opportunity
        obj.contact_email = contract.opportunity.contact.email
    else:
        obj = OpportunityFormObj(contract.department, contract.description, contact_email)
    return obj

def update_contract_with_spec(contract, form_data, company=None, clone=False):
    if clone:
        contract = ContractBase.clone(contract, parent_id=contract.parent_id, strip=False)
        db.session.add(contract)
        db.session.commit()

    spec_number = contract.get_spec_number()

    data = form_data
    new_spec = data.pop('spec_number', None)

    if new_spec:
        spec_number.key = 'Spec Number'
        spec_number.value = new_spec
    else:
        spec_number.key = 'Spec Number'
        spec_number.value = None
    contract.properties.append(spec_number)

    if company:
        contract.companies.append(company)

    contract.update(**data)

    return contract, spec_number

def parse_companies(companies):
    cleaned = []
    for company in companies.get('companies'):
        if company.get('company_name'):
            cleaned.append({
                'company_name': company.get('company_name')[1],
                'company_id': company.get('company_name')[0],
                'financial_id': company.get('controller_number')
            })
        else:
            cleaned.append({
                'company_name': company.get('new_company_name'),
                'company_id': -1,
                'financial_id': company.get('new_company_controller_number')
            })
    return cleaned

def get_attachment_filenames(attachments):
    filenames = []
    for attachment in attachments:
        try:
            return filenames.append(attachment.upload.data.filename)
        except AttributeError:
            continue
    return filenames if len(filenames) > 0 else None

def handle_form(form, form_name, stage_id, user, contract, current_stage):
    if form.validate_on_submit():
        action = ContractStageActionItem(
            contract_stage_id=stage_id, action_type=form_name,
            taken_by=user.id, taken_at=datetime.datetime.utcnow()
        )
        if form_name == 'activity':
            current_app.logger.info(
                'CONDUCTOR NOTE | New note on stage "{}" from contract "{}" (ID: {})'.format(
                    current_stage.name, contract.description, contract.id
                )
            )

            action.action_detail = {
                'note': form.data.get('note', ''),
                'stage_name': current_stage.name
            }

        elif form_name == 'update':
            current_app.logger.info(
                'CONDUCTOR EMAIL UPDATE | New update on stage "{}" from contract "{}" (ID: {})'.format(
                    current_stage.name, contract.description, contract.id
                )
            )

            action.action_detail = {
                'sent_to': form.data.get('send_to', ''),
                'body': form.data.get('body'),
                'subject': form.data.get('subject'),
                'stage_name': current_stage.name,
                'attachments': get_attachment_filenames(form.attachments.entries)
            }

            Notification(
                to_email=[i.strip() for i in form.data.get('send_to').split(';') if i != ''],
                from_email=current_user.email,
                cc_email=form.data.get('send_to_cc', []),
                subject=form.data.get('subject'),
                html_template='conductor/emails/email_update.html',
                body=form.data.get('body'),
                attachments=[i.upload.data for i in form.attachments.entries]
            ).send()

        elif form_name == 'post':
            current_app.logger.info(
                'CONDUCTOR BEACON POST | Beacon posting on stage "{}" from contract "{}" (ID: {})'.format(
                    current_stage.name, contract.description, contract.id
                )
            )

            label = 'created'
            if contract.opportunity:
                label = 'updated'

            form_data = fix_form_categories(request, form, Opportunity, None)
            # add the contact email, documents back on because it was stripped by the cleaning
            form_data['contact_email'] = form.data.get('contact_email')
            form_data['documents'] = form.documents
            # add the created_by_id
            form_data['created_from_id'] = contract.id
            # strip the is_public field from the form data, it's not part of the form
            form_data.pop('is_public')
            opportunity = build_opportunity(
                form_data, publish='publish', opportunity=contract.opportunity
            )

            action.action_detail = {
                'opportunity_id': opportunity.id, 'title': opportunity.title,
                'label': label
            }

        elif form_name == 'update-metadata':
            current_app.logger.info(
                'CONDUCTOR UPDATE METADATA | Contract update metadata on stage "{}" from contract "{}" (ID: {})'.format(
                    current_stage.name, contract.description, contract.id
                )
            )

            # remove the blank hidden field -- we don't need it
            data = form.data
            del data['all_blank']

            _, _ = update_contract_with_spec(contract, data)
            # this process pops off the spec number, so get it back
            data['spec_number'] = form.data.get('spec_number')

            # get department
            if form.data.get('department', None):
                data['department'] = form.data.get('department').name

            action.action_detail = data

        else:
            return False

        db.session.add(action)
        db.session.commit()
        return True

    return False

def build_action_log(stage_id, active_stage):
    '''Builds and properly orders an action log for a given stage
    '''
    actions = ContractStageActionItem.query.filter(
        ContractStageActionItem.contract_stage_id == stage_id
    ).order_by(db.text('taken_at asc')).all()

    actions = sorted(actions, key=lambda stage: stage.get_sort_key())

    return actions

def build_subscribers(contract):
    department_users = User.query.filter(
        User.department_id == contract.department_id,
        db.func.lower(Department.name) != 'equal opportunity review commission'
    ).all()

    county_purchasers = User.query.join(Role, User.role_id == Role.id).filter(
        Role.name == 'county'
    ).all()

    eorc = User.query.join(Department, User.department_id == Department.id).filter(
        db.func.lower(Department.name) == 'equal opportunity review commission'
    ).all()

    if contract.parent is None:
        followers = []
    else:
        followers = [i for i in contract.parent.followers if i not in department_users]

    subscribers = {
        'Department Users': department_users,
        'Followers': followers,
        'County Purchasers': [i for i in county_purchasers if i not in department_users],
        'EORC': eorc
    }
    return subscribers, sum([len(i) for i in subscribers.values()])

def assign_a_contract(contract, flow, user_id, clone=True):
    # if we don't have a flow, stop and throw an error
    if not flow:
        return False

    # if the contract is already assigned,
    # resassign it and continue on
    if contract.assigned_to and not contract.completed_last_stage():
        contract.assigned_to = user_id
        db.session.commit()

        current_app.logger.info('CONDUCTOR ASSIGN - old contract "{}" assigned to {} with flow {}'.format(
            contract.description, contract.assigned.email, contract.flow.flow_name
        ))

        return contract

    # otherwise, it's new work. perform the following:
    # 1. create a cloned version of the contract
    # 2. create the relevant contract stages
    # 3. transition into the first stage
    # 4. assign the contract to the user
    else:
        if clone:
            contract = ContractBase.clone(contract)
            db.session.add(contract)
            db.session.commit()
        try:
            stages, _, _ = create_contract_stages(flow.id, contract.id, contract=contract)
            actions = contract.transition(current_user)
            for i in actions:
                db.session.add(i)
            db.session.flush()
        except IntegrityError:
            # we already have the sequence for this, so just
            # rollback and pass
            db.session.rollback()
            pass

        contract.assigned_to = user_id
        db.session.commit()

        current_app.logger.info('CONDUCTOR ASSIGN - new contract "{}" assigned to {} with flow {}'.format(
            contract.description, contract.assigned.email, contract.flow.flow_name
        ))

        return contract

def reshape_metrics_csv_rollup(resultset, flow_id):
    '''Transform long data from database into rollup view for quick consumption

    Take in a result set (list of tuples), and return a dictionary of key-value
    pairs for each required field.
    '''
    pass
