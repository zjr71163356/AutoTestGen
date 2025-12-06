import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from bson import ObjectId
from bson.binary import Binary
from bson.decimal128 import Decimal128
from bson.regex import Regex
from dotenv import load_dotenv
import pymongo


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, ObjectId):
        return "ObjectId"
    if isinstance(value, Decimal128):
        return "Decimal128"
    if isinstance(value, Binary):
        return "Binary"
    if isinstance(value, Regex):
        return "Regex"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (list, tuple)):
        return "list"
    return value.__class__.__name__


def _summarize_document(doc: Dict[str, Any], acc: Dict[str, Dict[str, Any]]) -> None:
    for key, value in doc.items():
        entry = acc.setdefault(key, {"types": set()})
        entry["types"].add(_type_name(value))

        if isinstance(value, dict):
            nested = entry.setdefault("subfields", {})
            _summarize_document(value, nested)
        elif isinstance(value, (list, tuple)):
            item_types = entry.setdefault("item_types", set())
            item_schema = entry.setdefault("item_schema", {})
            if len(value) == 0:
                item_types.add("empty")
            for item in value:
                item_types.add(_type_name(item))
                if isinstance(item, dict):
                    _summarize_document(item, item_schema)


def _finalize_schema(schema: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    finalized: Dict[str, Any] = {}
    for key in sorted(schema):
        entry = schema[key]
        normalized: Dict[str, Any] = {"types": sorted(entry.get("types", []))}
        if "subfields" in entry:
            normalized["subfields"] = _finalize_schema(entry["subfields"])
        if "item_types" in entry:
            normalized["item_types"] = sorted(entry["item_types"])
        if entry.get("item_schema"):
            normalized["item_schema"] = _finalize_schema(entry["item_schema"])
        finalized[key] = normalized
    return finalized


def _serialize_indexes(index_info: Dict[str, Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for name, spec in index_info.items():
        keys = [{"field": field, "direction": direction} for field, direction in spec.get("key", [])]
        yield {
            "name": name,
            "keys": keys,
            "unique": bool(spec.get("unique", False)),
            "sparse": bool(spec.get("sparse", False)),
            "partialFilterExpression": spec.get("partialFilterExpression"),
        }


def summarize_collection(collection: pymongo.collection.Collection, app: str, sample_size: int) -> Dict[str, Any]:
    schema_acc: Dict[str, Dict[str, Any]] = defaultdict(dict)
    base_query = {"app": app}
    query_used = base_query

    try:
        total = collection.count_documents(base_query)
        cursor = collection.find(base_query).limit(sample_size)
        if total == 0:
            total = collection.count_documents({})
            cursor = collection.find({}).limit(sample_size)
            query_used = {}
    except Exception as exc:
        return {"error": f"query_failed: {exc}"}

    sampled = 0
    for doc in cursor:
        sampled += 1
        _summarize_document(doc, schema_acc)

    try:
        indexes = list(_serialize_indexes(collection.index_information()))
    except Exception as exc:
        indexes = [{"error": f"index_fetch_failed: {exc}"}]

    return {
        "count": total,
        "sampled": sampled,
        "query_filter": query_used,
        "fields": _finalize_schema(schema_acc),
        "indexes": indexes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the current MongoDB schema to JSON.")
    parser.add_argument("--app", default=None, help="APP_NAME filter; defaults to env APP_NAME")
    parser.add_argument("--db-name", default=None, help="MongoDB database name; defaults to URI target or myDatabase")
    parser.add_argument("--sample-size", type=int, default=200, help="Maximum documents to sample per collection")
    parser.add_argument("--output", default="report/db_schema.json", help="Output JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    load_dotenv(".env")
    app_name = args.app or os.getenv("APP_NAME") or "PETCLINIC"
    uri = os.getenv("ATLAS_URI")
    if not uri:
        raise RuntimeError("ATLAS_URI is not set; cannot connect to MongoDB.")

    client = pymongo.MongoClient(uri)
    try:
        default_db = client.get_default_database()
    except pymongo.errors.ConfigurationError:
        default_db = None
    if args.db_name:
        db = client[args.db_name]
    elif default_db:
        db = default_db
    else:
        db = client["myDatabase"]

    sample_size = max(1, args.sample_size)

    schema: Dict[str, Any] = {
        "app": app_name,
        "database": db.name,
        "sample_size": sample_size,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "collections": {},
    }

    for coll_name in sorted(db.list_collection_names()):
        schema["collections"][coll_name] = summarize_collection(db[coll_name], app_name, sample_size)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    print(f"Schema written to {output_path}")


if __name__ == "__main__":
    main()
