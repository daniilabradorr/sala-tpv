"""Preserve model validation while sharing one SQL check for stock conditions."""

from contextlib import nullcontext

from django.core.exceptions import FieldError, ValidationError
from django.db import DatabaseError, connections, models, router, transaction
from django.db.models.functions import Coalesce
from django.db.models.sql import Query
from django.db.models.sql.constants import SINGLE


def _check_conditions(condition, against, using):
    """Q.check semantics, but propagate SQL/fetch errors to the fallback.

    Django 5.2 Q.check treats DatabaseError as True. That must not approve
    several independent constraints at once. Keep its NULL semantics and
    savepoint, and let the caller run the original individual validators.
    """
    query = Query(None)
    for name, value in against.items():
        if not hasattr(value, "resolve_expression"):
            value = models.Value(value)
        query.add_annotation(value, name, select=False)
    query.add_annotation(models.Value(1), "_check")
    connection = connections[using]
    if connection.features.supports_comparing_boolean_expr:
        query.add_q(
            models.Q(Coalesce(condition, True, output_field=models.BooleanField()))
        )
    else:
        query.add_q(condition)
    compiler = query.get_compiler(using=using)
    context = (
        transaction.atomic(using=using) if connection.in_atomic_block else nullcontext()
    )
    with context:
        return compiler.execute_sql(SINGLE) is not None


def validate_stock_constraints(instance, exclude=None):
    """Validate all constraints; keep Django's individual errors on failure.

    full_clean still validates fields/FKs, clean(), uniqueness and constraints.
    Only standard CheckConstraint conditions share their successful SQL probe.
    No validation result is cached across instances, writes or transactions.
    """
    using = router.db_for_write(instance.__class__, instance=instance)
    errors = {}
    for model_class, constraints in instance.get_constraints():
        checks = [c for c in constraints if type(c) is models.CheckConstraint]
        checks_pass = False
        if len(checks) > 1:
            condition = models.Q()
            for check in checks:
                condition &= models.Q(check.condition)
            try:
                against = instance._get_field_expression_map(
                    meta=model_class._meta, exclude=exclude
                )
                checks_pass = _check_conditions(condition, against, using)
            except (FieldError, DatabaseError):
                pass

        for constraint in constraints:
            if checks_pass and type(constraint) is models.CheckConstraint:
                continue
            try:
                constraint.validate(model_class, instance, exclude=exclude, using=using)
            except ValidationError as error:
                # Match Model.validate_constraints, including field-specific
                # single-column unique errors and aggregated non-field errors.
                if (
                    getattr(error, "code", None) == "unique"
                    and len(constraint.fields) == 1
                ):
                    errors.setdefault(constraint.fields[0], []).append(error)
                else:
                    errors = error.update_error_dict(errors)
    if errors:
        raise ValidationError(errors)
