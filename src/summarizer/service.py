from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import anthropic
import logging

from src.config import get_settings
from src.devices.models import FirmwareVersion, DeviceModel
from src.devices import service as device_service

settings = get_settings()
logger = logging.getLogger(__name__)


def get_anthropic_client() -> anthropic.Anthropic:
    """Get Anthropic client."""
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def summarize_changelog(changelog: str, device_name: str) -> str:
    """
    Use Claude to summarize a firmware changelog.
    Returns a concise summary of the key changes.
    """
    if not changelog or not changelog.strip():
        return ""

    client = get_anthropic_client()

    prompt = f"""Summarize this firmware changelog for the {device_name} in 2-3 concise bullet points.
Focus on the most important changes that a user would care about (new features, bug fixes, improvements).
Keep each bullet point to one short sentence.

Changelog:
{changelog}

Summary:"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Error summarizing changelog: {e}")
        return ""


async def summarize_pending_changelogs(db: AsyncSession) -> int:
    """
    Find firmware versions with changelogs but no summaries and generate summaries.
    Returns count of summaries generated.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not configured, skipping summarization")
        return 0

    # Find firmware versions with changelog but no summary
    result = await db.execute(
        select(FirmwareVersion)
        .where(FirmwareVersion.changelog_raw.isnot(None))
        .where(FirmwareVersion.changelog_raw != "")
        .where(
            (FirmwareVersion.changelog_summary.is_(None))
            | (FirmwareVersion.changelog_summary == "")
        )
        .limit(10)  # Process in batches
    )
    pending = result.scalars().all()

    count = 0
    for firmware in pending:
        # Get device name for context
        device_result = await db.execute(
            select(DeviceModel).where(DeviceModel.id == firmware.device_model_id)
        )
        device = device_result.scalar_one_or_none()
        device_name = device.name if device else "device"

        summary = await summarize_changelog(firmware.changelog_raw, device_name)
        if summary:
            await device_service.update_firmware_summary(db, firmware.id, summary)
            count += 1
            logger.info(f"Generated summary for {device_name} v{firmware.version}")

    return count
