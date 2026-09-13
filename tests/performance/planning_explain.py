"""Trusted diagnostic source executed only in an isolated native operator process."""

SOURCE = """
import os
from app.application.services.business_access import BusinessAccess
from app.infrastructure.postgresql.authorization import ActorBinding
from app.infrastructure.postgresql.planning_summaries import read_project_summaries
from app.runtime import RuntimeResources
from app.security import create_access_service
from app.shared.config.authentication import AuthenticationConfig

resources = RuntimeResources.from_environment(os.environ)
resources.database.open()
try:
    service = create_access_service(resources, AuthenticationConfig.from_environment(os.environ))
    actor = service.actor(os.environ['LOAD_QUERY_COOKIE'])
    access = BusinessAccess(actor, service.policy)
    query = next(value for value in read_project_summaries.__code__.co_consts
                 if isinstance(value,str) and 'WITH scope AS' in value)
    def inspect(connection):
        ids = [row[0] for row in connection.execute('SELECT id FROM eppm.project ORDER BY id')]
        return connection.execute('EXPLAIN (FORMAT JSON) ' + query, (ids,)).fetchone()[0][0]
    plan = resources.database.run(inspect, bind=ActorBinding(access,resources.key))
    fields = {'Node Type','Parent Relationship','Subplan Name','Join Type','Relation Name',
              'Alias','Startup Cost','Total Cost','Plan Rows','Plan Width','Strategy','Index Name'}
    def safe(node):
        result = {key:value for key,value in node.items() if key in fields}
        if 'Plans' in node:
            result['Plans'] = [safe(child) for child in node['Plans']]
        return result
    print(json.dumps({'plan':safe(plan['Plan']), 'analyze':False, 'scope':'actual signed viewer'}))
finally:
    resources.database.close()
"""
