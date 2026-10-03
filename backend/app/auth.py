import bcrypt
from sqlalchemy.orm import Session

from .config import Settings
from .models import AdminUser


def seed_admin(db: Session, settings: Settings) -> None:
    user = db.get(AdminUser, settings.admin_username)
    password = settings.admin_password.get_secret_value().encode("utf-8")
    if user is None:
        password_hash = bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)).decode("ascii")
        db.add(AdminUser(username=settings.admin_username, password_hash=password_hash))
        db.commit()
    elif not verify_password(password.decode("utf-8"), user.password_hash):
        user.password_hash = bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)).decode("ascii")
        db.commit()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")
