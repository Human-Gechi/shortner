from urllib.parse import urlparse
import httpx
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from cache.redis_client import LinkCache
from log import get_logger
from src.utils.helpers import (
    normalize_url, 
    generate_code, 
    ensure_unique_code, 
    verify_password,
    password_hash
)
from src.app_models.models import Link
from src.config import get_settings

settings = get_settings()
logger = get_logger("url_service")

async def code_exists(db: AsyncSession, code: str) -> bool:
    result = await db.execute(select(Link).where(Link.code == code))
    return result.scalar_one_or_none() is not None

def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False

async def is_reachable(url: str) -> tuple[bool, str]:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.head(url, timeout=10, follow_redirects=True)
            return r.status_code < 400, "ok"
        except httpx.TimeoutException:
            return False, "URL timed out"
        except httpx.ConnectError:
            return False, "Could not connect to URL"
        except Exception:
            return False, "URL is unreachable"

async def create_short_link(original_url: str, 
                            db: AsyncSession, 
                            custom_alias: str | None = None,
                            password: str | None = None,
                            expires_at: datetime | None = None,
                            max_clicks: int | None = None):
    
    clean_url = normalize_url(original_url)
    if not is_valid_url(clean_url):
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    reachable, reason = await is_reachable(clean_url)
    if not reachable:
        raise HTTPException(status_code=422, detail=reason)
    
    if custom_alias:
        if await code_exists(db, custom_alias):
            raise HTTPException(status_code=409, detail="Alias already exists")
        if custom_alias in settings.RESERVED_ALIASES:
            raise HTTPException(status_code=409, detail="Alias is reserved")
        code = custom_alias
    else:
        code = await ensure_unique_code(db)
    

    hashed_pw = password_hash(password) if password else None
    
  
    short_url = f"{settings.DOMAIN}/{code}"
    
  
    link = Link(
        code=code,
        short_url=short_url,
        original_url=clean_url,
        password_hash=hashed_pw,
        expires_at=expires_at,
        max_clicks=max_clicks,
        is_active=True,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    
    LinkCache.set_destination(
        short_code=code,
        original_url=clean_url,
        expires_at=expires_at
    )
    
    return link

async def resolve_link(db: AsyncSession, short_code: str, request_info: Request):
    
    destination = LinkCache.get_destination(short_code)
    
    if not destination:
        result = await db.execute(select(Link).where(Link.code == short_code))
        link = result.scalar_one_or_none()
        
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        
        if not link.is_active:
            raise HTTPException(status_code=410, detail="Link has been deactivated")
        
        if link.expires_at and datetime.now(timezone.utc) > link.expires_at:
            raise HTTPException(status_code=410, detail="Link has expired")
        
        if link.max_clicks and link.click_count >= link.max_clicks:
            raise HTTPException(status_code=410, detail="Link has reached its click limit")
        
     
        if link.password_hash:
            submitted_password = request_info.headers.get("X-Link-Password")
            if not submitted_password:
                raise HTTPException(status_code=401, detail="This link requires a password")
            if not verify_password(link.password_hash, submitted_password):
                raise HTTPException(status_code=401, detail="Wrong password")
        
        destination = link.original_url
    
    return destination

async def record_click(db: AsyncSession, short_code: str, request_info: Request):
    try:   
        raw_ip = request_info.get('ip')
        ua_string = request_info.get('user_agent', '')
        referer = request_info.get('referer')

        if not raw_ip:
            logger.warning(f"Skipping click for {short_code}: No IP provided.")
            return None
    except Exception:
        pass
        