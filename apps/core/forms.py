def wire_field_accessibility(form):
    """Connect a bound form's controls to their rendered help and errors."""
    errors = form.errors if form.is_bound else {}
    for name, field in form.fields.items():
        control_id = field.widget.attrs.get("id", f"id_{name}")
        described_by = []
        if field.help_text:
            described_by.append(f"{control_id}-help")
        if name in errors:
            described_by.append(f"{control_id}-errors")
            field.widget.attrs["aria-invalid"] = "true"
        if described_by:
            field.widget.attrs["aria-describedby"] = " ".join(described_by)
