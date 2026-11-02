"""GTK editor for local smart playlist rules."""

import uuid

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from smart_playlists import (FIELD_LABELS, FIELDS, LIMIT_UNITS, NUMBER_OPERATORS,
                             SELECTIONS, TEXT_OPERATORS, validate_definition)


def _combo(options, active):
    combo = Gtk.ComboBoxText()
    for identifier, label in options:
        combo.append(identifier, label)
    combo.set_active_id(active)
    return combo


class RuleEditor:
    def __init__(self, owner, rule=None):
        self.owner = owner
        rule = rule or {'field': 'genre', 'operator': 'contains', 'value': ''}
        self.row = Gtk.Box(spacing=6)
        self.field = _combo(FIELD_LABELS, rule.get('field', 'genre'))
        self.row.pack_start(self.field, False, False, 0)
        self.operator = Gtk.ComboBoxText()
        self.row.pack_start(self.operator, False, False, 0)
        self.first = Gtk.Entry()
        self.first.set_width_chars(16)
        self.first.set_text(str(rule.get('value', '')))
        self.row.pack_start(self.first, True, True, 0)
        self.to_label = Gtk.Label(label='to')
        self.to_label.set_no_show_all(True)
        self.row.pack_start(self.to_label, False, False, 0)
        self.second = Gtk.Entry()
        self.second.set_width_chars(10)
        self.second.set_no_show_all(True)
        self.second.set_text(str(rule.get('end', '')))
        self.row.pack_start(self.second, False, False, 0)
        remove = Gtk.Button(label='−')
        remove.get_accessible().set_name('Remove rule')
        remove.connect('clicked', lambda *_: owner.remove_rule(self))
        self.row.pack_start(remove, False, False, 0)
        add = Gtk.Button(label='+')
        add.get_accessible().set_name('Add rule below')
        add.connect('clicked', lambda *_: owner.add_rule(after=self))
        self.row.pack_start(add, False, False, 0)
        self.field.connect('changed', self.field_changed)
        self.operator.connect('changed', self.operator_changed)
        self.field_changed(None, rule.get('operator'))

    def field_changed(self, _combo, desired=None):
        field = self.field.get_active_id() or 'genre'
        choices = TEXT_OPERATORS if FIELDS[field] == 'text' else NUMBER_OPERATORS
        numeric = FIELDS[field] == 'number'
        for entry in (self.first, self.second):
            entry.set_input_purpose(Gtk.InputPurpose.NUMBER if numeric else
                                    Gtk.InputPurpose.FREE_FORM)
        hint = ('0–5 stars' if field == 'user_rating' else
                'e.g. 2020' if field == 'year' else
                'Number' if numeric else 'Text')
        self.first.set_placeholder_text(hint)
        self.second.set_placeholder_text(hint)
        self.operator.remove_all()
        for identifier, label in choices:
            self.operator.append(identifier, label)
        self.operator.set_active_id(desired if desired in {item[0] for item in choices}
                                    else choices[0][0])
        self.operator_changed(None)

    def operator_changed(self, _combo):
        range_selected = self.operator.get_active_id() == 'range'
        self.to_label.set_visible(range_selected)
        self.second.set_visible(range_selected)

    def value(self):
        rule = {'field': self.field.get_active_id(),
                'operator': self.operator.get_active_id(),
                'value': self.first.get_text()}
        if rule['operator'] == 'range':
            rule['end'] = self.second.get_text()
        return rule


class SmartPlaylistDialog:
    def __init__(self, parent, existing=None, checked_label='Only checked songs'):
        self.existing = existing or {}
        self.dialog = Gtk.Dialog(title='Edit smart playlist' if existing else 'New smart playlist',
                                 transient_for=parent, modal=True)
        self.dialog.set_default_size(760, 440)
        self.dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL,
                                'OK', Gtk.ResponseType.OK)
        outer = self.dialog.get_content_area()
        outer.set_spacing(12)
        outer.set_border_width(16)
        name_row = Gtk.Box(spacing=10)
        name_row.pack_start(Gtk.Label(label='Name'), False, False, 0)
        self.name = Gtk.Entry()
        self.name.set_text(self.existing.get('name', ''))
        self.name.set_placeholder_text('Smart playlist name')
        name_row.pack_start(self.name, True, True, 0)
        outer.pack_start(name_row, False, False, 0)

        match_row = Gtk.Box(spacing=8)
        self.rules_enabled = Gtk.CheckButton()
        self.rules_enabled.set_active(self.existing.get('rules_enabled', True))
        match_row.pack_start(self.rules_enabled, False, False, 0)
        match_row.pack_start(Gtk.Label(label='Match'), False, False, 0)
        self.match = _combo((('all', 'all'), ('any', 'any')),
                            self.existing.get('match', 'all'))
        match_row.pack_start(self.match, False, False, 0)
        match_row.pack_start(Gtk.Label(label='of the following rules'), False, False, 0)
        outer.pack_start(match_row, False, False, 0)
        self.rule_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        rules_scroll = Gtk.ScrolledWindow()
        rules_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rules_scroll.set_min_content_height(150)
        rules_scroll.add(self.rule_box)
        outer.pack_start(rules_scroll, True, True, 0)
        self.rules = []
        for rule in self.existing.get('rules', []) or [None]:
            self.add_rule(rule=rule)
        self.rules_enabled.connect('toggled', lambda button: self.rule_box.set_sensitive(
            button.get_active()))
        self.rule_box.set_sensitive(self.rules_enabled.get_active())

        self.checked_only = Gtk.CheckButton(label=checked_label)
        self.checked_only.set_active(self.existing.get('checked_only', False))
        outer.pack_start(self.checked_only, False, False, 0)
        limit_row = Gtk.Box(spacing=8)
        self.limit_enabled = Gtk.CheckButton(label='Limit to')
        self.limit_enabled.set_active(self.existing.get('limit_enabled', False))
        limit_row.pack_start(self.limit_enabled, False, False, 0)
        self.amount = Gtk.SpinButton.new_with_range(1, 100000, 1)
        self.amount.set_value(self.existing.get('limit_amount', 25))
        limit_row.pack_start(self.amount, False, False, 0)
        self.unit = _combo(LIMIT_UNITS, self.existing.get('limit_unit', 'songs'))
        limit_row.pack_start(self.unit, False, False, 0)
        limit_row.pack_start(Gtk.Label(label='selected by'), False, False, 0)
        self.selected_by = _combo(SELECTIONS, self.existing.get('selected_by', 'random'))
        limit_row.pack_start(self.selected_by, False, False, 0)
        outer.pack_start(limit_row, False, False, 0)
        self.limit_enabled.connect('toggled', self.limit_changed)
        self.limit_changed(self.limit_enabled)
        self.error = Gtk.Label(xalign=0)
        outer.pack_start(self.error, False, False, 0)
        self.dialog.show_all()
        for rule in self.rules:
            rule.operator_changed(None)

    def add_rule(self, _button=None, after=None, rule=None):
        if len(self.rules) >= 32:
            self.error.set_text('A smart playlist can have up to 32 rules.')
            return
        editor = RuleEditor(self, rule)
        index = self.rules.index(after) + 1 if after in self.rules else len(self.rules)
        self.rules.insert(index, editor)
        self.rule_box.pack_start(editor.row, False, False, 0)
        self.rule_box.reorder_child(editor.row, index)
        editor.row.show_all()
        editor.operator_changed(None)

    def remove_rule(self, editor):
        self.rules.remove(editor)
        editor.row.destroy()

    def limit_changed(self, button):
        for widget in (self.amount, self.unit, self.selected_by):
            widget.set_sensitive(button.get_active())

    def run(self):
        try:
            while True:
                if self.dialog.run() != Gtk.ResponseType.OK:
                    return None
                data = {'id': self.existing.get('id') or str(uuid.uuid4()),
                        'name': self.name.get_text(),
                        'rules_enabled': self.rules_enabled.get_active(),
                        'match': self.match.get_active_id(),
                        'rules': ([rule.value() for rule in self.rules]
                                  if self.rules_enabled.get_active() else []),
                        'checked_only': self.checked_only.get_active(),
                        'limit_enabled': self.limit_enabled.get_active(),
                        'limit_amount': self.amount.get_value_as_int(),
                        'limit_unit': self.unit.get_active_id(),
                        'selected_by': self.selected_by.get_active_id()}
                try:
                    return validate_definition(data)
                except ValueError as exc:
                    self.error.set_text(str(exc))
        finally:
            self.dialog.destroy()
