"""Project management."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...models.application import Application, Project
from ..deps import get_current_user, record_audit, require_permission, verify_csrf
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from ...models.user import User

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _out(project: Project, db: Session) -> ProjectOut:
    count = (
        db.query(Application)
        .filter(Application.project_id == project.id, Application.deleted_at.is_(None))
        .count()
    )
    return ProjectOut.model_validate(project).model_copy(update={"application_count": count})


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.created_at).all()
    return [_out(p, db) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201, dependencies=[Depends(verify_csrf)])
def create_project(payload: ProjectCreate, request: Request,
                   user: User = Depends(require_permission("projects.write")),
                   db: Session = Depends(get_db)):
    if db.query(Project).filter(Project.name == payload.name, Project.deleted_at.is_(None)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A project with this name already exists")
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    record_audit(db, user, "projects.create", "project", str(project.id), {"name": project.name}, request)
    return _out(project, db)


@router.put("/{project_id}", response_model=ProjectOut, dependencies=[Depends(verify_csrf)])
def update_project(project_id: uuid.UUID, payload: ProjectUpdate, request: Request,
                   user: User = Depends(require_permission("projects.write")),
                   db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).first()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    record_audit(db, user, "projects.update", "project", str(project.id), {}, request)
    return _out(project, db)


@router.delete("/{project_id}", dependencies=[Depends(verify_csrf)])
def delete_project(project_id: uuid.UUID, request: Request,
                   user: User = Depends(require_permission("projects.write")),
                   db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).first()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    apps = db.query(Application).filter(Application.project_id == project.id,
                                        Application.deleted_at.is_(None)).count()
    if apps:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Project still has {apps} application(s). Move or delete them first.")
    project.deleted_at = utcnow()
    db.commit()
    record_audit(db, user, "projects.delete", "project", str(project.id), {"name": project.name}, request)
    return {"ok": True}
