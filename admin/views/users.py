# ruff: noqa: RUF012
from flask_admin.contrib.sqla import ModelView


class UserView(ModelView):
    can_delete = True
    can_create = False
    can_edit = True
    can_view_details = True
    edit_modal = True
    can_export = True
    details_modal = True
    export_types = ["csv", "xlsx", "json", "yaml"]

    column_searchable_list = ["id", "telegram_id", "username", "first_name", "last_name", "email"]
    column_filters = ["tier", "is_active", "created_at", "last_seen"]
    column_list = [
        "id",
        "telegram_id",
        "username",
        "first_name",
        "last_name",
        "full_name",
        "email",
        "tier",
        "quota_used",
        "quota_limit",
        "language",
        "is_active",
        "created_at",
        "last_seen",
    ]
    column_default_sort = ("created_at", True)