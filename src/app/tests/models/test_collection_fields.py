from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import CollectionField, CollectionFieldGroup, CollectionFieldType


class CollectionFieldGroupModelTest(TestCase):
    """Test case for the CollectionFieldGroup model."""

    def setUp(self):
        """Set up test data for CollectionFieldGroup model tests."""
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )

    def test_group_creation_defaults(self):
        """Test that a group is created with expected defaults."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Condition")

        self.assertEqual(group.user, self.user)
        self.assertEqual(group.name, "Condition")
        self.assertEqual(group.position, 0)

    def test_group_string_representation(self):
        """Test the string representation of a CollectionFieldGroup."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Condition")
        self.assertEqual(str(group), f"{self.user.username} - Condition")

    def test_group_ordering_by_position(self):
        """Test that groups are ordered by position."""
        second = CollectionFieldGroup.objects.create(
            user=self.user, name="Second", position=1
        )
        first = CollectionFieldGroup.objects.create(
            user=self.user, name="First", position=0
        )

        groups = list(CollectionFieldGroup.objects.filter(user=self.user))
        self.assertEqual(groups, [first, second])

    def test_group_cascade_on_user_delete(self):
        """Test that a group is deleted when its user is deleted."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Condition")

        self.user.delete()

        self.assertFalse(CollectionFieldGroup.objects.filter(id=group.id).exists())


class CollectionFieldModelTest(TestCase):
    """Test case for the CollectionField model."""

    def setUp(self):
        """Set up test data for CollectionField model tests."""
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )
        self.group = CollectionFieldGroup.objects.create(
            user=self.user, name="Condition"
        )

    def test_field_creation_defaults(self):
        """Test that a field is created with expected defaults."""
        field = CollectionField.objects.create(
            group=self.group,
            label="Grade",
            media_types=["book", "manga"],
        )

        self.assertEqual(field.group, self.group)
        self.assertEqual(field.label, "Grade")
        self.assertEqual(field.field_type, CollectionFieldType.TEXT)
        self.assertEqual(field.options, [])
        self.assertEqual(field.media_types, ["book", "manga"])
        self.assertEqual(field.position, 0)

    def test_field_string_representation(self):
        """Test the string representation of a CollectionField."""
        field = CollectionField.objects.create(
            group=self.group,
            label="Grade",
            media_types=["book"],
        )
        self.assertEqual(str(field), "Condition - Grade")

    def test_field_ordering_by_position(self):
        """Test that fields are ordered by position within a group."""
        second = CollectionField.objects.create(
            group=self.group, label="Second", media_types=["book"], position=1
        )
        first = CollectionField.objects.create(
            group=self.group, label="First", media_types=["book"], position=0
        )

        fields = list(CollectionField.objects.filter(group=self.group))
        self.assertEqual(fields, [first, second])

    def test_field_select_type_stores_options(self):
        """Test that select-type fields can store an options list."""
        field = CollectionField.objects.create(
            group=self.group,
            label="Cover Variant",
            field_type=CollectionFieldType.SELECT,
            options=["Standard", "Variant"],
            media_types=["comic"],
        )
        self.assertEqual(field.options, ["Standard", "Variant"])

    def test_field_cascade_on_group_delete(self):
        """Test that fields are deleted when their group is deleted."""
        field = CollectionField.objects.create(
            group=self.group, label="Grade", media_types=["book"]
        )

        self.group.delete()

        self.assertFalse(CollectionField.objects.filter(id=field.id).exists())
