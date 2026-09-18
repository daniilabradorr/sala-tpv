from pathlib import PurePosixPath
from uuid import uuid4


def asset_keys(*, business_id, entity_kind, entity_id, asset_id=None):
    asset_id = asset_id or uuid4()
    root = PurePosixPath(
        "businesses", str(business_id), entity_kind, str(entity_id), str(asset_id)
    )
    return {name: str(root / f"{name}.webp") for name in ("master", "thumb", "detail")}


def variant_key(master_key, variant):
    if variant not in {"master", "thumb", "detail"}:
        raise ValueError("Unknown media variant")
    return str(PurePosixPath(master_key).with_name(f"{variant}.webp"))
