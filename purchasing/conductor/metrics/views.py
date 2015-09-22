# -*- coding: utf-8 -*-

from flask import render_template, stream_with_context, Response, abort, jsonify

from purchasing.decorators import requires_roles

from purchasing.data.flows import Flow

from purchasing.conductor.metrics import blueprint

@blueprint.route('/')
@requires_roles('conductor', 'admin', 'superadmin')
def index():
    flows = Flow.query.all()
    return render_template('conductor/metrics/index.html', flows=flows)

@blueprint.route('/download/<int:flow_id>')
@requires_roles('conductor', 'admin', 'superadmin')
def download_csv_flow(flow_id):
    flow = Flow.query.get(flow_id)
    if flow:

        csv, headers = flow.reshape_metrics_granular()

        def stream():
            yield ','.join(headers) + '\n'
            for contract_id, values in csv.iteritems():
                yield ','.join([str(i) for i in values]) + '\n'

        resp = Response(
            stream_with_context(stream()),
            headers={
                "Content-Disposition": "attachment; filename=conductor-{}-metrics.csv".format(flow.flow_name)
            },
            mimetype='text/csv'
        )

        return resp
    abort(404)

@blueprint.route('/overview/<int:flow_id>')
@requires_roles('conductor', 'admin', 'superadmin')
def flow_overview(flow_id):
    flow = Flow.query.get(flow_id)
    if flow:
        return render_template('conductor/metrics/overview.html', flow_id=flow_id)
    abort(404)

@blueprint.route('/overview/<int:flow_id>/data')
@requires_roles('conductor', 'admin', 'superadmin')
def flow_data(flow_id):
    flow = Flow.query.get(flow_id)
    if flow:
        return jsonify(
            {'results': flow.build_metrics_data()}
        )
    abort(404)
