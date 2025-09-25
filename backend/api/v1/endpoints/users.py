from fastapi import Depends, APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from backend.core.database import get_db
from backend.core.security import get