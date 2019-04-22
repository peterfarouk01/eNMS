from copy import deepcopy
from flask import Flask
from git import Repo
from git.exc import GitCommandError
from logging import info
from napalm._SUPPORTED_DRIVERS import SUPPORTED_DRIVERS
from netmiko.ssh_dispatcher import CLASS_MAPPER, FILE_TRANSFER_MAP
from os import makedirs
from os.path import exists
from pathlib import Path, PosixPath
from string import punctuation
from typing import Any, Optional, Set
from yaml import dump, load, BaseLoader

from eNMS.controller import controller
from eNMS.default import create_default
from eNMS.modules import db
from eNMS.framework import delete_all, export, factory, fetch_all, fetch, get_one
from eNMS.properties import export_properties

NETMIKO_DRIVERS = sorted((driver, driver) for driver in CLASS_MAPPER)
NETMIKO_SCP_DRIVERS = sorted((driver, driver) for driver in FILE_TRANSFER_MAP)
NAPALM_DRIVERS = sorted((driver, driver) for driver in SUPPORTED_DRIVERS[1:])


def migrate_export(app: Flask, request: dict) -> bool:
    for cls_name in request["import_export_types"]:
        path = app.path / "migrations" / request["name"]
        if not exists(path):
            makedirs(path)
        with open(path / f"{cls_name}.yaml", "w") as migration_file:
            dump(export(cls_name), migration_file, default_flow_style=False)
    return True


def migrate_import(app: Flask, request: dict) -> str:
    status, types = "Import successful.", request["import_export_types"]
    workflows: list = []
    edges: list = []
    if request.get("empty_database_before_import", False):
        delete_all(*types)
    for cls in types:
        path = app.path / "migrations" / request["name"] / f"{cls}.yaml"
        with open(path, "r") as migration_file:
            objects = load(migration_file, Loader=BaseLoader)
            if cls == "Workflow":
                workflows = deepcopy(objects)
            if cls == "WorkflowEdge":
                edges = deepcopy(objects)
                continue
            for obj in objects:
                obj_cls = obj.pop("type") if cls == "Service" else cls
                # 1) We cannot import workflow edges before workflow, because a
                # workflow edge is defined by the workflow it belongs to.
                # Therefore, we import workflow before workflow edges but
                # strip off the edges, because they do not exist at this stage.
                # Edges will be defined later on upon importing workflow edges.
                # 2) At this stage, we cannot import jobs, because if workflows
                # A (ID 1) and B (ID 2) are created, and B is added to A as a
                # subworkflow, we won't be able to create A as B is one of its
                # jobs and does not exist yet. To work around this, we will
                # strip off the jobs at this stage, and reimport workflows a
                # second time at the end.
                if cls == "Workflow":
                    obj["edges"], obj["jobs"] = [], []
                try:
                    factory(obj_cls, **obj)
                except Exception as e:
                    info(f"{str(obj)} could not be imported ({str(e)})")
                    status = "Partial import (see logs)."
    for workflow in workflows:
        workflow["edges"] = []
        try:
            factory("Workflow", **workflow)
        except Exception as e:
            info(f"{str(workflow)} could not be imported ({str(e)})")
            status = "Partial import (see logs)."
    for edge in edges:
        try:
            factory("WorkflowEdge", **edge)
        except Exception as e:
            info(f"{str(edge)} could not be imported ({str(e)})")
            status = "Partial import (see logs)."
    print("fix")
    if request.get("empty_database_before_import", False):
        create_default(app)
    return status


def scheduler_job(
    job_id: int,
    aps_job_id: Optional[str] = None,
    targets: Optional[Set["Device"]] = None,
    payload: Optional[dict] = None,
) -> None:
    with controller.app.app_context():
        task = fetch("Task", creation_time=aps_job_id)
        job = fetch("Job", id=job_id)
        if targets:
            targets = {fetch("Device", id=device_id) for device_id in targets}
        results, now = job.try_run(targets=targets, payload=payload)
        parameters = get_one("Parameters")
        if job.push_to_git and parameters.git_automation:
            path_git_folder = Path.cwd() / "git" / "automation"
            with open(path_git_folder / job.name, "w") as file:
                file.write(str_dict(results))
            repo = Repo(str(path_git_folder))
            try:
                repo.git.add(A=True)
                repo.git.commit(m=f"Automatic commit ({job.name})")
            except GitCommandError:
                pass
            repo.remotes.origin.push()
        if task and not task.frequency:
            task.is_active = False
        db.session.commit()


def str_dict(input: Any, depth: int = 0) -> str:
    tab = "\t" * depth
    if isinstance(input, list):
        result = "\n"
        for element in input:
            result += f"{tab}- {str_dict(element, depth + 1)}\n"
        return result
    elif isinstance(input, dict):
        result = ""
        for key, value in input.items():
            result += f"\n{tab}{key}: {str_dict(value, depth + 1)}"
        return result
    else:
        return str(input)


def strip_all(input: str) -> str:
    return input.translate(str.maketrans("", "", f"{punctuation} "))