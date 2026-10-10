# -*- coding: utf-8 -*-

"""
Processing/Altering individual files with permissions, ownership, file date, etc.
"""

import os
import subprocess
import zipfile
from typing import List, Union

from backend.base.definitions import FileDate
from backend.base.files import (set_file_date, set_volume_folder_owner_group,
                                set_volume_folder_permissions)
from backend.base.logging import LOGGER
from backend.implementations.root_folders import RootFolders
from backend.internals.db import get_db
from backend.internals.db_models import FilesDB
from backend.internals.settings import Settings


def mass_set_file_date(
    volume_id: int,
    issue_id: Union[int, None] = None,
    filepath_filter: Union[List[str], None] = None
) -> None:
    """Set the date of the issue files to the release date of the issue.

    Args:
        volume_id (int): The ID of the volume for which to set the file dates.

        issue_id (Union[int, None], optional): The ID of the issue for which
            to set the file dates, instead of all volume files.
            Defaults to None.

        filepath_filter (Union[List[str], None], optional): Only process files
            that are in the list.
            Defaults to None.
    """
    if Settings().sv.change_file_date == FileDate.NONE:
        # Setting disabled
        return

    issue_filter = ""
    filepath_sql_filter = ""
    if issue_id:
        issue_filter = "AND i.id = :issue_id"
    if filepath_filter:
        filepath_list = "'" + "','".join(filepath_filter) + "'"
        filepath_sql_filter = f"AND f.filepath IN ({filepath_list})"

    cursor = get_db()
    cursor.execute(f"""
        SELECT f.filepath, i.date
        FROM files f
        INNER JOIN issues_files if
        INNER JOIN issues i
        ON f.id = if.file_id
            AND if.issue_id = i.id
        WHERE i.volume_id = :volume_id
            {issue_filter}
            {filepath_sql_filter}
            AND i.date IS NOT NULL
        """,
        {
            "volume_id": volume_id,
            "issue_id": issue_id or -1
        }
    )

    for filepath, date in cursor:
        set_file_date(filepath, date)

    return


def mass_set_permissions(volume_id: int) -> None:
    """Set the (chmod) permissions of a volume folder, folders between the root
    folder and the volume folder, its sub-folders and its files. The folders are
    set according to the setting value. The files are set similarly but without
    the execution bit.

    Args:
        volume_id (int): The ID of the volume for which to set the permissions.
    """
    permissions = Settings().sv.chmod_folder
    if not permissions:
        # Setting disabled
        return

    volume_folder, root_folder_id = get_db().execute(
        "SELECT folder, root_folder FROM volumes WHERE id = ?",
        (volume_id,)
    ).fetchone()

    set_volume_folder_permissions(
        volume_folder,
        RootFolders()[root_folder_id],
        permissions
    )

    return


def mass_set_ownership(volume_id: int) -> None:
    """Set the (chown) group owner of the volume folder, folders between the root
    folder and the volume folder, its sub-folders and its files.

    Args:
        volume_id (int): The ID of the volume for which to set the ownership.
    """
    group = Settings().sv.chown_group
    if not group:
        # Setting disabled
        return

    volume_folder, root_folder_id = get_db().execute(
        "SELECT folder, root_folder FROM volumes WHERE id = ?",
        (volume_id,)
    ).fetchone()

    set_volume_folder_owner_group(
        volume_folder,
        RootFolders()[root_folder_id],
        group
    )

    return


def embed_comicinfo(filepath: str, volume_id: int, force: bool = False) -> None:
    """Embed ComicInfo.xml metadata into a CBZ file using ComicTagger.

    Args:
        filepath (str): The path to the file to be tagged.
        volume_id (int): The ID of the volume the file belongs to.
        force (bool, optional): Overwrite existing metadata. 
            Defaults to False.
    """
    if not os.path.exists(filepath):
        return

    # Only tag CBZ files
    if not filepath.lower().endswith('.cbz'):
        return

    # Skip if ComicInfo.xml already exists
    if not force and zipfile.is_zipfile(filepath):
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                if 'ComicInfo.xml' in zf.namelist():
                    LOGGER.info(f"ComicInfo.xml already embedded in {filepath}, skipping.")
                    return
        except zipfile.BadZipFile:
            LOGGER.warning(f"Bad zip file: {filepath}")

    covered_issues = FilesDB.issues_covered(filepath)
    if not covered_issues:
        return
    
    # Local to prevent circular import
    from backend.implementations.volumes import Issue

    try:
        issue_obj = Issue.from_volume_and_calc_number(volume_id, covered_issues[0])
        cv_issue_id = issue_obj.get_data().comicvine_id
    except Exception as e:
        LOGGER.warning(f"Could not retrieve issue metadata for {filepath}: {e}")
        return

    cv_api_key = Settings().sv.comicvine_api_key

    LOGGER.info(f'Running ComicTagger on {filepath} with CV Issue ID {cv_issue_id}')

    subprocess.run([
        "comictagger",
        "-s",
        "-t", "cr",
        "-o",
        "--id", str(cv_issue_id),
        "--cv-api-key", str(cv_api_key),
        "--config", "/app/db/.ComicTagger",
        filepath
    ], check=False, stderr=subprocess.DEVNULL)
    

def mass_tag(volume_id: int, issue_id: int | None = None, force: bool = False) -> None:
    """Apply metadata tags to all applicable files within a volume or issue.

    Args:
        volume_id (int): The ID of the volume for which to tag files.
        issue_id (Union[int, None], optional): The ID of the issue for which
            to tag files, instead of all volume files. 
            Defaults to None.
        force (bool, optional): Overwrite existing metadata. 
            Defaults to False.
    """
    # Local to prevent circular import
    from backend.implementations.volumes import Volume
    
    if issue_id:
        files = [f["filepath"] for f in Volume(volume_id).get_issue(issue_id).get_files()]
    else:
        files = [f["filepath"] for f in Volume(volume_id).get_all_files()]

    for filepath in files:
        embed_comicinfo(filepath, volume_id, force=force)
    return


def mass_process_files(
    volume_id: int,
    issue_id: Union[int, None] = None,
    filepath_filter: Union[List[str], None] = None
) -> None:
    """Process individual files (and folders), mostly by setting properties.
    Sets things like file date, permissions and ownership, based on the settings.

    Args:
        volume_id (int): The ID of the volume for which the files should be
            processed.

        issue_id (Union[int, None], optional): The ID of the issue for which the
            files should specifically be processed. Defaults to None.

        filepath_filter (Union[List[str], None], optional): Only process files
            that are in the list.
            Defaults to None.
    """
    mass_set_file_date(volume_id, issue_id, filepath_filter)
    mass_set_permissions(volume_id)
    mass_set_ownership(volume_id)
    return
