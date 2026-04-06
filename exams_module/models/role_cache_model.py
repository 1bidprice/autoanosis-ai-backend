"""
Autoanosis Role Cache Model
===========================
Persistent store for WordPress-pushed user roles.
Table: aa_role_cache

This table is completely separate from all exams data structures.
It is written exclusively by POST /internal/role-sync and read
exclusively by the doctor/admin authorization gate.

Schema:
  uid         BIGINT PRIMARY KEY   — WordPress user ID
  roles_json  TEXT NOT NULL        — JSON array of role slugs e.g. '["doctor"]'
  synced_at   TIMESTAMP NOT NULL   — when the push was received
  expires_at  TIMESTAMP NOT NULL   — synced_at + TTL; access denied after this

TTL is controlled by AUTOA_ROLE_CACHE_TTL env var (default 300 seconds).
"""
from sqlalchemy import Column, BigInteger, Text, DateTime
from sqlalchemy.sql import func
from exams_module.db.base import Base


class RoleCache(Base):
    __tablename__ = "aa_role_cache"

    uid        = Column(BigInteger, primary_key=True, nullable=False)
    roles_json = Column(Text, nullable=False)
    synced_at  = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
