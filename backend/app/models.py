"""Normalized data model for USA JOB HUNTER.

Verification vocabulary (used across tables):
  verification_status: VERIFIED | PARTIALLY_VERIFIED | UNKNOWN | CONFLICTING
  email_status:        VERIFIED | PUBLISHED_ELSEWHERE | DO_NOT_USE | NONE
  job_status:          ACTIVE | POSSIBLY_ACTIVE | CLOSED | UNKNOWN
  j1_status:           CONFIRMED_J1_VACANCY | CONFIRMED_J1_EMPLOYER | INTERNATIONAL_FRIENDLY |
                       NEEDS_CONFIRMATION | NO_SPONSORSHIP | UNKNOWN
"""
from datetime import datetime, date

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.utcnow()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ---------------------------------------------------------------- users / profile
class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(500))
    years_experience: Mapped[float | None] = mapped_column(Float)
    education: Mapped[list] = mapped_column(JSON, default=list)        # [{degree, field, school, status}]
    licenses: Mapped[list] = mapped_column(JSON, default=list)
    subjects: Mapped[list] = mapped_column(JSON, default=list)
    grade_levels: Mapped[list] = mapped_column(JSON, default=list)
    leadership: Mapped[list] = mapped_column(JSON, default=list)
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    awards: Mapped[list] = mapped_column(JSON, default=list)
    research_stem: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    work_authorization: Mapped[str] = mapped_column(String(255), default="Requires J-1 Teacher Exchange pathway")
    preferred_states: Mapped[list] = mapped_column(JSON, default=list)
    min_salary: Mapped[int | None] = mapped_column(Integer)
    has_us_license: Mapped[bool] = mapped_column(Boolean, default=False)
    has_us_drivers_license: Mapped[bool] = mapped_column(Boolean, default=False)
    active_resume_id: Mapped[int | None] = mapped_column(Integer)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)   # file bytes (the cloud keeps no files)
    version_label: Mapped[str] = mapped_column(String(100), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ---------------------------------------------------------------- organizations
class District(Base, TimestampMixin):
    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    city: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(1000))
    # How the official website was confirmed: {url, page_title, how_found, check, verification_status, checked_at}
    website_evidence: Mapped[dict | None] = mapped_column(JSON)
    careers_url: Mapped[str | None] = mapped_column(String(1000))
    hr_directory_url: Mapped[str | None] = mapped_column(String(1000))
    j1_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    j1_evidence: Mapped[list] = mapped_column(JSON, default=list)   # [{url, quote, checked_at}]
    source_url: Mapped[str | None] = mapped_column(String(1000))
    verification_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("name", "state", name="uq_district_name_state"),)


class School(Base, TimestampMixin):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(10))
    website: Mapped[str | None] = mapped_column(String(1000))
    staff_directory_url: Mapped[str | None] = mapped_column(String(1000))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    verification_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    district: Mapped["District | None"] = relationship()


# ---------------------------------------------------------------- jobs
class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(500), index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(100))
    job_title: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str | None] = mapped_column(String(100))
    subjects: Mapped[list] = mapped_column(JSON, default=list)
    grade_level: Mapped[str | None] = mapped_column(String(100))
    employer_name: Mapped[str | None] = mapped_column(String(500))
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    zip: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    employment_type: Mapped[str | None] = mapped_column(String(100))
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_text: Mapped[str | None] = mapped_column(String(500))
    date_posted: Mapped[date | None] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date)
    closing_text: Mapped[str | None] = mapped_column(String(255))
    job_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN", index=True)
    status_reason: Mapped[str | None] = mapped_column(String(500))
    official_job_url: Mapped[str | None] = mapped_column(String(1000))
    application_url: Mapped[str | None] = mapped_column(String(1000))
    job_description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    certification_requirements: Mapped[str | None] = mapped_column(Text)
    j1_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN", index=True)
    j1_evidence: Mapped[list] = mapped_column(JSON, default=list)
    match_score: Mapped[int | None] = mapped_column(Integer, index=True)
    match_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    field_evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # field -> {value, source_url, source_type, verification_status, verified_at, confidence}
    verification_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    date_discovered: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_in_scan: Mapped[datetime | None] = mapped_column(DateTime)

    school: Mapped["School | None"] = relationship()
    district: Mapped["District | None"] = relationship()
    sources: Mapped[list["JobSource"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    contact_links: Mapped[list["JobContact"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    verifications: Mapped[list["JobVerification"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobSource(Base):
    """Every URL where a canonical job was seen (duplicate detection keeps them all)."""
    __tablename__ = "job_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    source_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(60))  # OFFICIAL_DISTRICT | OFFICIAL_ATS | STATE_BOARD | DISCOVERY
    tier: Mapped[int] = mapped_column(Integer, default=2)
    external_id: Mapped[str | None] = mapped_column(String(100))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    job: Mapped["Job"] = relationship(back_populates="sources")
    __table_args__ = (UniqueConstraint("job_id", "url", name="uq_job_source_url"),)


class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    # Only stored when the source itself publishes it (e.g. "Mr. Almasy"); never inferred from a name.
    honorific: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(500))
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    contact_type: Mapped[str] = mapped_column(String(60), default="HR")  # PRINCIPAL | RECRUITER | HR | ...
    email: Mapped[str | None] = mapped_column(String(255))
    email_status: Mapped[str] = mapped_column(String(30), default="NONE")
    email_source_url: Mapped[str | None] = mapped_column(String(1000))
    # Result of asking the school's mail server whether the mailbox exists (no email sent):
    # EXISTS | NOT_FOUND | CATCH_ALL | NO_MAIL_SERVER | UNKNOWN ; None = not checked yet
    mailbox_status: Mapped[str | None] = mapped_column(String(20))
    mailbox_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    mailbox_detail: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(64))
    phone_source_url: Mapped[str | None] = mapped_column(String(1000))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_type: Mapped[str | None] = mapped_column(String(60))
    verification_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    # Soft delete: the contact's job links are removed (so it disappears from every job, letter and export)
    # and kept here so Undo can put them back. Scans never re-link a deleted contact.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_links: Mapped[list | None] = mapped_column(JSON)
    school: Mapped["School | None"] = relationship()
    district: Mapped["District | None"] = relationship()


class JobContact(Base):
    __tablename__ = "job_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    # JOB_POSTER | VACANCY_CONTACT | PRINCIPAL | CAMPUS_ADMINISTRATOR | REGIONAL_RECRUITER |
    # DISTRICT_RECRUITER | INTERNATIONAL_RECRUITER | VISA_COORDINATOR | HR_ADMINISTRATOR | GENERAL_HR_ONLY
    relationship_type: Mapped[str] = mapped_column("relationship", String(60))
    confidence: Mapped[str] = mapped_column(String(10), default="LOW")  # HIGH | MEDIUM | LOW
    evidence_url: Mapped[str | None] = mapped_column(String(1000))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    job: Mapped["Job"] = relationship(back_populates="contact_links")
    contact: Mapped["Contact"] = relationship()
    __table_args__ = (UniqueConstraint("job_id", "contact_id", "relationship", name="uq_job_contact_rel"),)


class JobVerification(Base):
    """Audit trail: every check (automatic or manual) that touched a job."""
    __tablename__ = "job_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    check_type: Mapped[str] = mapped_column(String(40))  # STATUS | CONTACT | J1 | MANUAL | SOURCE
    target: Mapped[str | None] = mapped_column(String(100))  # vacancy / principal / email / j1 ...
    result: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    http_status: Mapped[int | None] = mapped_column(Integer)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    job: Mapped["Job"] = relationship(back_populates="verifications")


# ---------------------------------------------------------------- J-1
class J1Program(Base, TimestampMixin):
    __tablename__ = "j1_programs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization: Mapped[str] = mapped_column(String(500))
    # DESIGNATED_J1_SPONSOR | RECRUITMENT_AGENCY | DISTRICT_EMPLOYER
    organization_type: Mapped[str] = mapped_column(String(40))
    states_served: Mapped[list] = mapped_column(JSON, default=list)
    subjects_recruited: Mapped[list] = mapped_column(JSON, default=list)
    official_website: Mapped[str | None] = mapped_column(String(1000))
    teacher_program_url: Mapped[str | None] = mapped_column(String(1000))
    address: Mapped[str | None] = mapped_column(String(500))
    headquarters_state: Mapped[str | None] = mapped_column(String(2))
    contact_person: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    fees_if_public: Mapped[str | None] = mapped_column(Text)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    last_verified: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- applications / CRM
class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    school: Mapped[str | None] = mapped_column(String(500))
    district: Mapped[str | None] = mapped_column(String(500))
    state: Mapped[str | None] = mapped_column(String(2))
    position: Mapped[str | None] = mapped_column(String(500))
    salary: Mapped[str | None] = mapped_column(String(255))
    job_url: Mapped[str | None] = mapped_column(String(1000))
    date_posted: Mapped[date | None] = mapped_column(Date)
    date_applied: Mapped[date | None] = mapped_column(Date)
    contact_person: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    resume_version: Mapped[str | None] = mapped_column(String(255))
    cover_letter_version: Mapped[str | None] = mapped_column(String(255))
    # DISCOVERED SAVED APPLYING APPLIED FOLLOW_UP INTERVIEW SECOND_INTERVIEW OFFER HIRED REJECTED WITHDRAWN POSITION_CLOSED
    application_status: Mapped[str] = mapped_column(String(30), default="SAVED", index=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    interview_date: Mapped[datetime | None] = mapped_column(DateTime)
    interview_timezone: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    documents_sent: Mapped[list] = mapped_column(JSON, default=list)
    response_received: Mapped[bool] = mapped_column(Boolean, default=False)
    offer_salary: Mapped[str | None] = mapped_column(String(255))
    visa_status: Mapped[str | None] = mapped_column(String(255))
    cover_letter_text: Mapped[str | None] = mapped_column(Text)
    email_text: Mapped[str | None] = mapped_column(Text)
    # Soft delete: set when the user deletes the record, cleared by Undo. Deleted records are hidden everywhere.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Dates (ISO yyyy-mm-dd) the user applied to this job again; listed in the Re-applied card.
    reapplied_dates: Mapped[list | None] = mapped_column(JSON, default=list)
    job: Mapped["Job | None"] = relationship()
    events: Mapped[list["ApplicationEvent"]] = relationship(back_populates="application", cascade="all, delete-orphan",
                                                            order_by="ApplicationEvent.occurred_at")
    interviews: Mapped[list["Interview"]] = relationship(viewonly=True, order_by="Interview.starts_at_utc")


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))  # FIRST_EMAIL APPLICATION FOLLOW_UP RESPONSE INTERVIEW STATUS_CHANGE NOTE
    description: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    application: Mapped["Application"] = relationship(back_populates="events")


class Interview(Base, TimestampMixin):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime)
    us_timezone: Mapped[str] = mapped_column(String(64))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    round_label: Mapped[str | None] = mapped_column(String(100))
    interviewer: Mapped[str | None] = mapped_column(String(255))
    interviewer_role: Mapped[str | None] = mapped_column(String(255))
    school: Mapped[str | None] = mapped_column(String(500))
    meeting_url: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    application: Mapped["Application | None"] = relationship()


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(60), default="OTHER")  # RESUME COVER_LETTER LICENSE TRANSCRIPT CERTIFICATE OTHER
    stored_path: Mapped[str] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ---------------------------------------------------------------- alerts
class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # HIGH_MATCH | CONFIRMED_J1 | STATE | SALARY | VERIFIED_RECRUITER_EMAIL | VERIFIED_PRINCIPAL_EMAIL
    rule_type: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("rule_id", "job_id", name="uq_alert_rule_job"),)


# ---------------------------------------------------------------- AI contact lookups (cost cap + 60-day cache)
class AILookup(Base):
    __tablename__ = "ai_lookups"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), index=True)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    detail: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


# ---------------------------------------------------------------- Outbox (emails waiting for the user's approval)
class OutboxEmail(Base):
    """An application email prepared automatically for a new opening. Nothing is sent until the user approves it."""
    __tablename__ = "outbox_emails"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    to_email: Mapped[str] = mapped_column(String(255))
    to_name: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    attach_resume: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)   # PENDING | SENT | SKIPPED | FAILED
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    job: Mapped["Job"] = relationship(viewonly=True)


# ---------------------------------------------------------------- Engineering jobs
class EngJob(Base, TimestampMixin):
    """Engineering (industry) and Engineering Instructor openings, kept apart from the teaching jobs."""
    __tablename__ = "eng_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(20), index=True)        # INDUSTRY | INSTRUCTOR
    source_key: Mapped[str] = mapped_column(String(300), unique=True)   # e.g. gh:samsara:12345
    source: Mapped[str] = mapped_column(String(200))                   # e.g. "Greenhouse – Samsara"
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(1000))
    posted: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(20), default="UNKNOWN")    # ENTRY | MID | SENIOR | UNKNOWN
    years_required: Mapped[int | None] = mapped_column(Integer)
    sponsorship: Mapped[str] = mapped_column(String(20), default="UNKNOWN")  # OFFERED | NOT_OFFERED | UNKNOWN
    citizenship_required: Mapped[bool] = mapped_column(Boolean, default=False)
    phd_required: Mapped[bool] = mapped_column(Boolean, default=False)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    match_score: Mapped[int | None] = mapped_column(Integer, index=True)
    match: Mapped[dict] = mapped_column(JSON, default=dict)                  # {why: [], gaps: [], breakdown: []}
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)  # ACTIVE | CLOSED
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_on: Mapped[date | None] = mapped_column(Date)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))      # K-12 engineering teacher jobs
    # Pay exactly as the employer posted it (structured field or the posting text); never estimated.
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_interval: Mapped[str | None] = mapped_column(String(10))     # YEAR | HOUR | MONTH
    salary_text: Mapped[str | None] = mapped_column(String(120))
    work_mode: Mapped[str | None] = mapped_column(String(10))           # REMOTE | HYBRID | ONSITE | UNKNOWN
    remote_scope: Mapped[str | None] = mapped_column(String(10))        # remote boards: US | WORLDWIDE


# ---------------------------------------------------------------- H-1B sponsors
class H1BEmployer(Base, TimestampMixin):
    """An employer from the user's H-1B sponsor list, checked for current Math/STEM openings."""
    __tablename__ = "h1b_employers"
    id: Mapped[int] = mapped_column(primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500))
    avg_salary: Mapped[int | None] = mapped_column(Integer)          # as given in the user's list
    careers_url: Mapped[str] = mapped_column(String(1000))
    state: Mapped[str | None] = mapped_column(String(2))           # only when shown by the employer's own board
    board_type: Mapped[str | None] = mapped_column(String(40))     # applitrack | edjoin | bamboohr | none
    board_ref: Mapped[str | None] = mapped_column(String(300))     # slug / districtID / company
    board_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str | None] = mapped_column(String(30))         # LIVE | SCANS_ONLY | UNREADABLE
    status_detail: Mapped[str | None] = mapped_column(String(500))
    total_openings: Mapped[int | None] = mapped_column(Integer)    # all postings on the live board
    job_ids: Mapped[list] = mapped_column(JSON, default=list)      # current Math/STEM openings
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)


# ---------------------------------------------------------------- scanning
class ScanSource(Base, TimestampMixin):
    """Registry of places the scanner visits. Editable from the Scan Monitor."""
    __tablename__ = "scan_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    connector: Mapped[str] = mapped_column(String(60))  # schoolspring | applitrack | jsonld_page
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(255))
    tier: Mapped[int] = mapped_column(Integer, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(60))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_jobs_found: Mapped[int | None] = mapped_column(Integer)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # QUICK | FULL | VERIFY_JOBS | VERIFY_CONTACTS | J1 | CLOSED_CHECK
    trigger: Mapped[str] = mapped_column(String(20), default="MANUAL")  # MANUAL | SCHEDULED
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING | COMPLETED | FAILED
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[str | None] = mapped_column(String(500))


class ScanLog(Base):
    __tablename__ = "scan_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    source_name: Mapped[str | None] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1500))
    http_status: Mapped[int | None] = mapped_column(Integer)
    crawl_status: Mapped[str] = mapped_column(String(40))   # FETCHED | ROBOTS_BLOCKED | ERROR | SKIPPED
    parser_status: Mapped[str | None] = mapped_column(String(40))  # PARSED | NO_MATCH | PARSE_ERROR
    jobs_discovered: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=now)


Index("ix_jobs_state_status", Job.state, Job.job_status)
