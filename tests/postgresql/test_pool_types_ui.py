"""Pool type modal and mandatory pool-selector persistence with real services."""
from app.domain.resources.pool_types import PoolType
from app.main import create_resource_pool_service
from tests.postgresql.test_resource_pool_ui import database, access, dialog
from tests.postgresql.ui import native_screen


def type_dialog(resources, access, invocation):
    return native_screen(f"""
from app.main import create_resource_pool_service
from app.presentation.pages.pool_types import _edit_pool_type, _delete_pool_type
service = create_resource_pool_service(runtime, access=access)
{invocation}
""", resources, access).run()


def test_pool_dialog_requires_type_defaults_to_human_and_retains_car(database, access):
    pools = create_resource_pool_service(database, access=access)
    app = dialog(database, access, '_open_add_pool_dialog(service)')
    assert app.selectbox(key='new_pool_type').value == 1
    app.text_input[0].input('Fleet')
    app.selectbox(key='new_pool_type').set_value(2)
    app.button[0].click().run()
    assert not app.exception
    pool = pools.get_all_pools()[0]
    assert pool.pool_type_id == 2
    app = dialog(database, access, f'_open_edit_pool_dialog(service, {pool.id})')
    assert app.selectbox(key=f'pool_type_{pool.id}').value == 2
    app.selectbox(key=f'pool_type_{pool.id}').set_value(1)
    next(button for button in app.button if button.label.endswith('Save Changes')).click().run()
    assert not app.exception and pools.get_pool_by_id(pool.id).pool_type_id == 1


def test_type_dialog_creates_child_and_excludes_it_from_parent_choices(database, access):
    pools = create_resource_pool_service(database, access=access)
    app = type_dialog(database, access, '_edit_pool_type(service)')
    assert not app.exception
    app.text_input[0].input('Van')
    app.selectbox[0].set_value(2)
    app.button[0].click().run()
    assert not app.exception
    child = pools.get_all_pool_types()[-1]
    assert child.name == 'Van' and child.parent_pool_type_id == 2
    app = type_dialog(database, access, '_edit_pool_type(service, service.get_all_pool_types()[1])')
    assert 'Van' not in app.selectbox[0].options and 'Car' not in app.selectbox[0].options
    app = type_dialog(database, access, '_delete_pool_type(service, service.get_all_pool_types()[1])')
    app.button[0].click().run()
    assert app.error and not app.exception
