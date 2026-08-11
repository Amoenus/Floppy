from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from app.management.commands.populate_runtime_data import Command
from app.models import Item, MediaTypes, Sources


class PopulateRuntimeDataCommandTests(TestCase):
    @patch.object(Command, "_update_item_runtime")
    def test_processes_tvdb_tv_items(self, mock_update_item_runtime):
        item = Item.objects.create(
            media_id="tvdb-show",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="TVDB Show",
            image="https://example.com/show.jpg",
            runtime_minutes=None,
        )

        call_command("populate_runtime_data", "--delay", "0")

        mock_update_item_runtime.assert_called_once_with(item)
