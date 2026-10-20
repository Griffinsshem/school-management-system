import pytest
from argon2 import PasswordHasher

from app.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)

GOOD_PASSWORD = "correct horse battery"


def test_hash_is_argon2id_with_the_chosen_parameters():
    password_hash = hash_password(GOOD_PASSWORD)

    assert password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert GOOD_PASSWORD not in password_hash


def test_same_password_gets_a_different_hash_each_time():
    assert hash_password(GOOD_PASSWORD) != hash_password(GOOD_PASSWORD)


def test_correct_password_verifies():
    assert verify_password(hash_password(GOOD_PASSWORD), GOOD_PASSWORD) is True


@pytest.mark.parametrize("attempt", ["correct horse batterY", "", " " + GOOD_PASSWORD])
def test_wrong_password_does_not_verify(attempt):
    assert verify_password(hash_password(GOOD_PASSWORD), attempt) is False


@pytest.mark.parametrize("broken_hash", ["", "not-a-hash", "$argon2id$v=19$m=19456,t=2,p=1$abc"])
def test_broken_hash_returns_false_instead_of_crashing(broken_hash):
    assert verify_password(broken_hash, GOOD_PASSWORD) is False


def test_overlong_password_is_refused_without_hashing():
    assert verify_password(hash_password(GOOD_PASSWORD), "x" * (MAX_PASSWORD_LENGTH + 1)) is False


def test_older_weaker_hash_still_verifies_and_is_flagged_for_rehash():
    old_hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    old_hash = old_hasher.hash(GOOD_PASSWORD)

    assert verify_password(old_hash, GOOD_PASSWORD) is True
    assert needs_rehash(old_hash) is True
    assert needs_rehash(hash_password(GOOD_PASSWORD)) is False


@pytest.mark.parametrize(
    "password",
    ["x" * (MIN_PASSWORD_LENGTH - 1), " " * MIN_PASSWORD_LENGTH, "x" * (MAX_PASSWORD_LENGTH + 1)],
)
def test_passwords_breaking_the_rules_are_rejected(password):
    with pytest.raises(PasswordPolicyError):
        validate_password(password)
    with pytest.raises(PasswordPolicyError):
        hash_password(password)


@pytest.mark.parametrize(
    "password",
    ["x" * MIN_PASSWORD_LENGTH, "x" * MAX_PASSWORD_LENGTH, "plain words are fine"],
)
def test_passwords_within_the_rules_are_accepted(password):
    validate_password(password)
