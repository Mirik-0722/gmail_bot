from cryptography.fernet import Fernet

from gmail_bot.storage import Storage


def test_storage_roundtrip_and_encryption(tmp_path):
    db = tmp_path / "t.db"
    st = Storage(str(db), Fernet.generate_key().decode())
    st.save(1, "a@gmail.com", "secret-pw", 10)

    assert b"secret-pw" not in db.read_bytes()
    s = st.get(1)
    assert (s.email, s.app_password, s.last_uid) == ("a@gmail.com", "secret-pw", 10)

    st.update_last_uid(1, 20)
    st.save(1, "b@gmail.com", "pw2", 30)  # qayta sozlash
    assert [(u.email, u.last_uid) for u in st.all()] == [("b@gmail.com", 30)]

    st.delete(1)
    assert st.get(1) is None
