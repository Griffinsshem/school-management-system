"""Terminal commands. Run them with `flask --app app <command>`."""

import click
from flask import Flask, current_app
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth import rate_limit
from app.auth.passwords import PasswordPolicyError, hash_password
from app.auth.sessions import utcnow
from app.extensions import db
from app.models import Membership, School, User, UserSession
from app.models.membership import ROLES
from app.models.school import normalize_school_code
from app.models.user import MAX_NAME_LENGTH, EmailFormatError, normalize_email, validate_email


def register_cli(app: Flask) -> None:
    @app.cli.command("create-platform-admin")
    @click.option("--email", prompt="Email", help="The administrator's email address.")
    @click.option("--name", "full_name", prompt="Full name", help="The administrator's name.")
    def create_platform_admin(email: str, full_name: str) -> None:
        """Create a platform administrator.

        The password is always typed at a hidden prompt, never passed as an
        option, so it cannot end up in shell history.
        """
        email = normalize_email(email)
        try:
            validate_email(email)
        except EmailFormatError as error:
            raise click.ClickException(str(error)) from None

        full_name = full_name.strip()
        if not full_name or len(full_name) > MAX_NAME_LENGTH:
            raise click.ClickException(f"Full name must be 1 to {MAX_NAME_LENGTH} characters.")

        if db.session.scalar(select(User.id).where(User.email == email)) is not None:
            raise click.ClickException("A user with that email already exists.")

        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        try:
            password_hash = hash_password(password)
        except PasswordPolicyError as error:
            raise click.ClickException(str(error)) from None

        user = User(
            email=email,
            full_name=full_name,
            password_hash=password_hash,
            is_platform_admin=True,
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise click.ClickException("A user with that email already exists.") from None

        current_app.logger.info("Platform administrator created: user_id=%s", user.id)
        click.echo(f"Platform administrator created: {email}")

    @app.cli.command("add-membership")
    @click.option("--email", required=True, help="The user's email address.")
    @click.option("--school-code", required=True, help="The school's code.")
    @click.option("--role", required=True, type=click.Choice(ROLES), help="The role to give.")
    def add_membership(email: str, school_code: str, role: str) -> None:
        """Give an existing user a role in a school (until invitations exist).

        Re-adding a role that was deactivated turns it back on.
        """
        user = db.session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None:
            raise click.ClickException("No user with that email exists.")
        school = db.session.scalar(
            select(School).where(School.code == normalize_school_code(school_code))
        )
        if school is None:
            raise click.ClickException("No school with that code exists.")

        membership = db.session.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.school_id == school.id,
                Membership.role == role,
            )
        )
        if membership is not None and membership.is_active:
            raise click.ClickException("That user already has that role in that school.")
        if membership is not None:
            membership.is_active = True
        else:
            membership = Membership(user_id=user.id, school_id=school.id, role=role)
            db.session.add(membership)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise click.ClickException("That user already has that role in that school.") from None

        current_app.logger.info(
            "Membership added: membership_id=%s user_id=%s school_id=%s role=%s",
            membership.id,
            user.id,
            school.id,
            role,
        )
        click.echo(f"{email} is now {role} at {school.name}.")

    @app.cli.command("prune-sessions")
    def prune_sessions() -> None:
        """Delete expired sessions and old failed-login records."""
        now = utcnow()
        idle_cutoff = now - current_app.config["SESSION_IDLE_TIMEOUT"]
        sessions = db.session.execute(
            delete(UserSession).where(
                or_(UserSession.expires_at <= now, UserSession.last_seen_at <= idle_cutoff)
            )
        ).rowcount
        attempts = rate_limit.prune(now)
        db.session.commit()
        click.echo(f"Deleted {sessions} expired sessions and {attempts} old login attempts.")
