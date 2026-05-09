"""코드 작업 CRUD."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.software import CodeTask, TaskStatusEnum
from schemas.software import TaskCreate, TaskResponse

router = APIRouter()


@router.post(
    "/",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="코드 작업 등록",
)
async def create_task(
    data: TaskCreate,
    db:   AsyncSession = Depends(get_db),
) -> CodeTask:
    task = CodeTask(
        id=str(uuid.uuid4()),
        title=data.title,
        description=data.description,
        language=data.language,
        status=TaskStatusEnum.PENDING,
    )
    db.add(task)
    await db.flush()
    return task


@router.get("/{task_id}", response_model=TaskResponse, summary="작업 단건 조회")
async def get_task(
    task_id: str,
    db:      AsyncSession = Depends(get_db),
) -> CodeTask:
    task = await db.scalar(select(CodeTask).where(CodeTask.id == task_id))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="작업을 찾을 수 없습니다.",
        )
    return task


@router.get("/", response_model=list[TaskResponse], summary="최근 작업 목록")
async def list_tasks(
    limit: int = 30,
    db:    AsyncSession = Depends(get_db),
) -> list[CodeTask]:
    rows = (
        await db.scalars(
            select(CodeTask).order_by(CodeTask.created_at.desc()).limit(limit)
        )
    ).all()
    return list(rows)
