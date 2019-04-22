from collections import Counter
from contextlib import contextmanager
from flask import Flask
from flask.wrappers import Response
from flask_login import current_user
from logging import info
from pathlib import Path, PosixPath
from sqlalchemy import and_
from sqlalchemy.orm import Session
from typing import Generator, Set
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from xlrd import open_workbook
from xlrd.biffh import XLRDError
from xlwt import Workbook

from eNMS.framework import (
    delete,
    delete_all,
    factory,
    fetch,
    fetch_all,
    fetch_all_visible,
    get,
    get_one,
    objectify,
    post,
)
from eNMS.models import classes, service_classes
from eNMS.modules import (
    bp,
    db,
    ldap_client,
    scheduler,
    tacacs_client,
    USE_LDAP,
    USE_TACACS,
)
from eNMS.properties import (
    cls_to_properties,
    default_diagrams_properties,
    google_earth_styles,
    link_subtype_to_color,
    pretty_names,
    private_properties,
    property_types,
    reverse_pretty_names,
    subtype_sizes,
    table_fixed_columns,
    table_properties,
    type_to_diagram_properties,
)


class ImportExportController:
    def get_cluster_status(self) -> dict:
        return {
            attr: [getattr(instance, attr) for instance in fetch_all("Instance")]
            for attr in ("status", "cpu_load")
        }

    def get_counters(self, property: str, type: str) -> Counter:
        property = reverse_pretty_names.get(property, property)
        return Counter(str(getattr(instance, property)) for instance in fetch_all(type))

    def allowed_file(self, name: str, allowed_modules: Set[str]) -> bool:
        allowed_syntax = "." in name
        allowed_extension = name.rsplit(".", 1)[1].lower() in allowed_modules
        return allowed_syntax and allowed_extension

    def object_import(self, request: dict, file: FileStorage) -> str:
        if request["replace"]:
            delete_all("Device")
        result = "Topology successfully imported."
        if self.allowed_file(secure_filename(file.filename), {"xls", "xlsx"}):
            book = open_workbook(file_contents=file.read())
            for obj_type in ("Device", "Link"):
                try:
                    sheet = book.sheet_by_name(obj_type)
                except XLRDError:
                    continue
                properties = sheet.row_values(0)
                for row_index in range(1, sheet.nrows):
                    values = dict(zip(properties, sheet.row_values(row_index)))
                    values["dont_update_pools"] = True
                    try:
                        factory(obj_type, **values).serialized
                    except Exception as e:
                        info(f"{str(values)} could not be imported ({str(e)})")
                        result = "Partial import (see logs)."
                db.session.commit()
        for pool in fetch_all("Pool"):
            pool.compute_pool()
        db.session.commit()
        info("Inventory import: Done.")
        return result

    def object_export(self, request: dict, path_app: PosixPath) -> bool:
        workbook = Workbook()
        filename = request["export_filename"]
        if "." not in filename:
            filename += ".xls"
        for obj_type in ("Device", "Link"):
            sheet = workbook.add_sheet(obj_type)
            for index, property in enumerate(export_properties[obj_type]):
                sheet.write(0, index, property)
                for obj_index, obj in enumerate(fetch_all(obj_type), 1):
                    sheet.write(obj_index, index, getattr(obj, property))
        workbook.save(path_app / "projects" / filename)
        return True