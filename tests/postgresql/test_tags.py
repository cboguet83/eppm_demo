"""Native tag catalogs, scoped paging, owner guards and concurrent callbacks."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event

import psycopg
import pytest

from app.application.exceptions import TagConflictError, TagStorageError
from app.application.services.tags import TagService
from app.domain.access.models import AccessDenied
from app.domain.tags.models import ProjectTag, ResourcePoolTag, TagDictionary, TagGroup, TaskTag
from app.infrastructure.postgresql.tags import PostgresTagGateway, PostgresTagStore


def service(authorized, user_id=4):
    return TagService(PostgresTagGateway(authorized.database, authorized.key, access=authorized.binding(user_id).access))


@pytest.fixture
def tags(authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id) VALUES (1,1,'Build','2026-09-01','2026-09-02',(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current)),(2,2,'Review','2026-09-01','2026-09-02',(SELECT id FROM eppm.project_plan WHERE project_id=2 AND is_current)),(3,3,'Hidden task','2026-09-01','2026-09-02',(SELECT id FROM eppm.project_plan WHERE project_id=3 AND is_current))")
        connection.execute("INSERT INTO eppm.resource_pool(name) VALUES ('Pool')")
    return service(authorized)


def test_catalog_crud_counts_all_assignment_kinds_and_preserves_cross_group_contract(tags):
    group = tags.create_tag_group(TagGroup(tag_group_name=' Business classification '))
    tag = tags.create_tag(TagDictionary(tag=' Critical ', tag_group_id=group))
    pt = tags.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    tt = tags.create_task_tag(TaskTag(task_id=1, tag_id=tag, free_tag=' Urgent '))
    pool = tags.create_resource_pool_tag(ResourcePoolTag(pool_id=1, tag_id=tag))
    assert tags.get_tag_group_by_id(group).tag_group_name == 'Business classification'
    assert tags.get_tag_group_for_tag(tag).id == group
    assert tags.get_tag_by_id(tag).tag == 'Critical'
    assert tags.get_all_tag_groups()[0].tag_count == tags.count_tags_by_group(group) == 1
    assert tags.get_all_tags()[0].usage_count == tags.count_tag_usages(tag) == 3
    assert tags.get_all_project_tags()[0].project_name == 'Editable'
    assert tags.get_all_task_tags()[0].task_name == 'Build'
    assert tags.get_all_resource_pool_tags()[0].pool_name == 'Pool'
    assert tags.get_project_tags_by_project(1)[0].tag_name == 'Critical'
    assert tags.get_task_tags_by_task(1)[0].free_tag == 'Urgent'
    assert tags.get_resource_pool_tags(1)[0].tag_id == tag
    assert tags.create_resource_pool_tag(ResourcePoolTag(pool_id=1, tag_id=tag)) == pool
    assert tags.update_tag_group(TagGroup(group, 'Renamed'))
    assert tags.update_tag(TagDictionary(tag, 'Changed', group))
    assert tags.get_tag_by_id(tag).tag == 'Changed'
    with pytest.raises(ValueError, match='dictionary tags'):
        tags.delete_tag_group(group)
    assert tags.delete_resource_pool_tag(pool)
    assert tags.delete_tag(tag)
    assert tags.get_project_tag_by_id(pt) is None and tags.get_task_tag_by_id(tt) is None
    assert tags.delete_tag_group(group)


def test_selectors_match_normalized_group_names_and_return_only_reference_fields(tags, authorized):
    for label in ('Project_Tags', 'Task Tags', 'Other'):
        group = tags.create_tag_group(TagGroup(tag_group_name=label))
        tags.create_tag(TagDictionary(tag=label, tag_group_id=group))
    assert tags.get_project_tag_group_tags()[0].tag == 'Project_Tags'
    assert tags.get_task_tag_group_tags()[0].tag == 'Task Tags'
    assert tags.get_tags_by_group_name(' project_tag ')[0].usage_count == 0
    reader = service(authorized, 1)
    assert reader.project_tag_choices()[0].tag == 'Project_Tags'
    assert reader.task_tag_choices()[0].tag == 'Task Tags'
    assert [row.id for row in reader.project_choices()] == [1, 2]
    assert [row.id for row in reader.search_task_choices()] == [2, 1]
    assert reader.search_task_choices('#1')[0].task_name == 'Build'
    assert reader.search_task_choices('EDITABLE')[0].id == 1
    assert reader.search_task_choices('build', limit=0)[0].id == 1
    assert reader.get_task_choice(1).project_name == 'Editable'
    assert reader.get_task_choice(3) is None
    assert reader.search_task_choices("' OR 1=1 --") == []
    for action in (reader.get_all_tag_groups, reader.get_all_tags, reader.get_all_resource_pool_tags,
                   lambda: reader.create_tag(TagDictionary(tag='Denied'))):
        with pytest.raises(AccessDenied):
            action()


def test_missing_records_and_assignment_updates_keep_existing_contracts(tags):
    assert tags.get_tag_group_by_id(999) is None
    assert tags.get_tag_group_for_tag(999) is None
    assert tags.get_tag_by_id(999) is None
    for record, update in ((TagGroup(tag_group_name='Missing'), tags.update_tag_group),
                           (TagDictionary(tag='Missing'), tags.update_tag),
                           (ProjectTag(project_id=1, free_tag='Missing'), tags.update_project_tag),
                           (TaskTag(task_id=1, free_tag='Missing'), tags.update_task_tag)):
        assert not update(record)
        assert not update(replace(record, id=999))
    for delete in (tags.delete_tag, tags.delete_tag_group, tags.delete_resource_pool_tag,
                   tags.delete_project_tag, tags.delete_task_tag):
        assert not delete(999)
    assert tags.get_task_tags_by_task_ids([]) == tags.get_project_tags_by_project_ids([]) == {}
    assert tags.get_task_tags_by_task_ids([None]) == {}
    pt = tags.create_project_tag(ProjectTag(project_id=1, free_tag='First'))
    tt = tags.create_task_tag(TaskTag(task_id=1, free_tag='First'))
    assert tags.update_project_tag(ProjectTag(pt, 2, free_tag='Changed'))
    assert tags.update_task_tag(TaskTag(tt, 2, free_tag='Changed'))
    assert tags.get_project_tag_by_id(pt).project_id == tags.get_task_tag_by_id(tt).task_id == 2
    assert tags.delete_project_tag(pt) and tags.delete_task_tag(tt)
    with pytest.raises(TagConflictError):
        tags.create_task_tag(TaskTag(task_id=1, tag_id=999))


def test_dictionary_parent_failure_restores_all_assignment_deletes(tags, authorized):
    tag = tags.create_tag(TagDictionary(tag='Protected'))
    tags.create_project_tag(ProjectTag(project_id=1, tag_id=tag))
    tags.create_task_tag(TaskTag(task_id=1, tag_id=tag))
    tags.create_resource_pool_tag(ResourcePoolTag(pool_id=1, tag_id=tag))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""CREATE FUNCTION eppm.reject_tag_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'private failure detail' USING ERRCODE='23514'; END $$""")
        connection.execute('CREATE TRIGGER reject_tag_delete BEFORE DELETE ON eppm.tag_dictionnary FOR EACH ROW EXECUTE FUNCTION eppm.reject_tag_delete()')
    with pytest.raises(TagConflictError) as error:
        tags.delete_tag(tag)
    assert 'private failure' not in str(error.value)
    assert tags.count_tag_usages(tag) == 3


def test_scope_filters_counts_pages_labels_and_batched_links_before_returning_rows(tags, authorized):
    tag = tags.create_tag(TagDictionary(tag='Shared dictionary'))
    projects, tasks = [], []
    for owner in (1, 2, 3):
        projects.append(tags.create_project_tag(ProjectTag(project_id=owner, tag_id=tag, free_tag=f'project {owner}')))
        tasks.append(tags.create_task_tag(TaskTag(task_id=owner, tag_id=tag, free_tag=f'task {owner}')))
    reader = service(authorized, 1)
    assert len(reader.get_all_project_tags()) == len(reader.get_all_task_tags()) == 2
    assert reader.get_project_tags_by_project(3) == reader.get_task_tags_by_task(3) == []
    assert reader.get_project_tag_by_id(projects[2]) is None and reader.get_task_tag_by_id(tasks[2]) is None
    page = reader.get_task_tags_page(page_size=1)
    assert page.total == page.filtered_total == page.pages == 2
    assert reader.get_task_tags_page(search='Hidden').filtered_total == 0
    assert reader.get_task_tags_page(filters={'task_name': 'Hidden'}).rows == []
    assert reader.get_project_tags_by_project_ids([1, 3, 999])[3] == []
    assert reader.get_project_tags_by_project_ids([1])[1][0]['project_id'] == 1
    assert reader.get_task_tags_by_task_ids([1, 3])[3] == []
    assert reader.get_task_tags_by_task_ids([1])[1][0]['tag_name'] == 'Shared dictionary'
    gateway = PostgresTagGateway(authorized.database, authorized.key, access=authorized.binding(1).access)
    assert gateway.run(lambda store: store.count_tag_usages(tag)) == 4
    assert gateway.run(lambda store: store.get_all_tags())[0].usage_count == 4


def test_assignment_mutations_check_both_previous_and_requested_project_owners(tags, authorized):
    reader = service(authorized, 1)
    editable_pt = tags.create_project_tag(ProjectTag(project_id=1, free_tag='Editable'))
    readonly_pt = tags.create_project_tag(ProjectTag(project_id=2, free_tag='Read only'))
    hidden_pt = tags.create_project_tag(ProjectTag(project_id=3, free_tag='Hidden'))
    editable_tt = tags.create_task_tag(TaskTag(task_id=1, free_tag='Editable'))
    readonly_tt = tags.create_task_tag(TaskTag(task_id=2, free_tag='Read only'))
    hidden_tt = tags.create_task_tag(TaskTag(task_id=3, free_tag='Hidden'))
    for action in (lambda: reader.create_project_tag(ProjectTag(project_id=2, free_tag='Denied')),
                   lambda: reader.create_task_tag(TaskTag(task_id=3, free_tag='Denied')),
                   lambda: reader.update_project_tag(ProjectTag(editable_pt, 2, free_tag='Move')),
                   lambda: reader.update_project_tag(ProjectTag(readonly_pt, 1, free_tag='Steal')),
                   lambda: reader.update_task_tag(TaskTag(editable_tt, 2, free_tag='Move')),
                   lambda: reader.update_task_tag(TaskTag(readonly_tt, 1, free_tag='Steal')),
                   lambda: reader.delete_project_tag(readonly_pt), lambda: reader.delete_task_tag(readonly_tt)):
        with pytest.raises(AccessDenied):
            action()
    assert not reader.delete_project_tag(hidden_pt) and not reader.delete_task_tag(hidden_tt)
    assert reader.update_project_tag(ProjectTag(editable_pt, 1, free_tag='Saved'))
    assert reader.update_task_tag(TaskTag(editable_tt, 1, free_tag='Saved'))
    assert reader.delete_project_tag(editable_pt) and reader.delete_task_tag(editable_tt)


def test_paging_uses_literal_filters_numeric_ids_stable_sort_and_bounded_selectors(tags, authorized):
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute("""INSERT INTO eppm.project_task(id,project_id,task_name,start_date,end_date,project_plan_id)
            SELECT n,1,'Task '||n,'2026-09-01'::date,'2026-09-02'::date,(SELECT id FROM eppm.project_plan WHERE project_id=1 AND is_current) FROM generate_series(1001,1350) n""")
        connection.execute("""INSERT INTO eppm.task_tag(task_id,free_tag)
            SELECT n,CASE WHEN n=1001 THEN 'Rare 100%_tag' ELSE 'Common' END FROM generate_series(1001,1350) n""")
    tags.create_task_tag(TaskTag(task_id=3, free_tag='Hidden'))
    reader = service(authorized, 1)
    first, second = reader.get_task_tags_page(), reader.get_task_tags_page(page=2)
    assert first.total == 350 and first.pages == 4 and len(first.rows) == 100
    assert not {row.id for row in first.rows} & {row.id for row in second.rows}
    assert reader.get_task_tags_page(filters={'free_tag': '100%_', 'project_name': 'edit'}).rows[0].task_id == 1001
    assert reader.get_task_tags_page(search="' OR 1=1 --").filtered_total == 0
    assert reader.get_task_tags_page(sort='bad SQL').rows == first.rows
    assert reader.get_task_tags_page(page=99).page == 4
    assert reader.get_task_tags_page(page_size=999).page_size == 200
    assert reader.get_task_tags_page(page_size=0).page_size == 1
    assert reader.get_task_tags_page(filters={'unknown': 'ignored'}).total == 350
    assert [row.id for row in reader.get_task_tags_page(sort='free_tag', ascending=True).rows] == list(range(2, 102))
    assert reader.get_task_tags_page(filters={'id': '350'}).rows[0].id == 350
    assert len(reader.search_task_choices(limit=999)) == 100


def test_page_counts_and_rows_share_a_snapshot_during_concurrent_delete(tags, authorized, monkeypatch):
    first = tags.create_task_tag(TaskTag(task_id=1, free_tag='First'))
    second = tags.create_task_tag(TaskTag(task_id=1, free_tag='Second'))
    ready, changed = Event(), Event()
    original = PostgresTagStore._rows
    def paused(store, model, query, params=()):
        if 'LIMIT %s OFFSET %s' in query:
            ready.set()
            assert changed.wait(10)
        return original(store, model, query, params)
    monkeypatch.setattr(PostgresTagStore, '_rows', paused)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(tags.get_task_tags_page)
        assert ready.wait(10)
        try:
            tags.delete_task_tag(first)
        finally:
            changed.set()
        page = future.result()
    assert page.total == len(page.rows) == 2
    assert [row.id for row in page.rows] == [second, first]


def test_concurrent_duplicate_pool_assignments_return_the_same_identity(tags, authorized):
    tag = tags.create_tag(TagDictionary(tag='Shared'))
    barrier, attempts = Barrier(2), [0, 0]
    class GatedGateway(PostgresTagGateway):
        def __init__(self, index):
            super().__init__(authorized.database, authorized.key, access=authorized.binding(4).access)
            self.index = index
        def run(self, operation, **options):
            def callback(store):
                attempts[self.index] += 1
                if attempts[self.index] == 1:
                    barrier.wait(timeout=10)
                return operation(store)
            return super().run(callback, **options)
    def assign(index):
        return TagService(GatedGateway(index)).create_resource_pool_tag(ResourcePoolTag(pool_id=1, tag_id=tag))
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(assign, range(2)))
    assert result[0] == result[1] and sum(attempts) >= 3
    assert len(tags.get_resource_pool_tags(1)) == 1


def test_tag_storage_outage_is_safe(tags, authorized, caplog):
    authorized.database.close()
    with pytest.raises(TagStorageError) as error:
        tags.get_all_tags()
    assert 'postgresql://' not in str(error.value) + caplog.text


def test_text_sort_preserves_null_placement_ascii_case_and_id_tiebreaks(tags):
    tag = tags.create_tag(TagDictionary(tag='Dictionary'))
    identities = [tags.create_task_tag(TaskTag(task_id=1, tag_id=tag, free_tag=value))
                  for value in (None, 'alpha', 'ALPHA', 'Zebra', 'éclair', 'Éclair')]
    ascending = tags.get_task_tags_page(sort='free_tag', ascending=True)
    assert [row.id for row in ascending.rows] == [identities[index] for index in (0, 1, 2, 3, 5, 4)]
    descending = tags.get_task_tags_page(sort='free_tag')
    assert [row.id for row in descending.rows] == [identities[index] for index in (4, 5, 3, 2, 1, 0)]
    assert tags.get_task_tags_page(search='ALPHA').filtered_total == 2
    assert tags.get_task_tags_page(search='éclair').filtered_total == 1
    empty = tags.get_task_tags_page(search='absent', page=99)
    assert empty.rows == [] and empty.page == empty.pages == 1 and empty.filtered_total == 0


def test_retry_preserves_original_pool_assignment_if_caller_mutates_the_command(tags, authorized):
    tag = tags.create_tag(TagDictionary(tag='Original'))
    with psycopg.connect(authorized.setup.operator_url) as connection:
        connection.execute('CREATE SEQUENCE eppm.tag_attempt')
        connection.execute('GRANT USAGE ON SEQUENCE eppm.tag_attempt TO eppm_runtime')
        connection.execute("""CREATE FUNCTION eppm.retry_tag_once() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF nextval('eppm.tag_attempt')=1 THEN RAISE EXCEPTION 'Known rollback' USING ERRCODE='40001'; END IF;
            RETURN NEW; END $$""")
        connection.execute('CREATE TRIGGER retry_tag_once BEFORE INSERT ON eppm.resource_pool_tag FOR EACH ROW EXECUTE FUNCTION eppm.retry_tag_once()')
    submitted, attempts = ResourcePoolTag(pool_id=1, tag_id=tag), []
    class ChangedInputGateway(PostgresTagGateway):
        def run(self, operation, **options):
            def callback(store):
                attempts.append(1)
                if len(attempts) == 2:
                    submitted.pool_id = 999
                return operation(store)
            return super().run(callback, **options)
    actor_service = TagService(ChangedInputGateway(authorized.database, authorized.key, access=authorized.binding(4).access))
    assignment = actor_service.create_resource_pool_tag(submitted)
    assert submitted.pool_id == 999 and len(attempts) == 2
    assert tags.get_resource_pool_tags(1)[0].id == assignment
