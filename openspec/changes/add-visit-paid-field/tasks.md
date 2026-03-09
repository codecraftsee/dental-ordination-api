## 1. Model

- [x] 1.1 Add `paid = Column(Boolean, default=False, server_default="0", nullable=False)` to `Visit` in `app/models/visit.py`
- [x] 1.2 Add `Boolean` to the SQLAlchemy imports in `app/models/visit.py`

## 2. Schemas

- [x] 2.1 Add `paid: bool = False` to `VisitBase` in `app/schemas/visit.py`
- [x] 2.2 Add `paid: Optional[bool] = None` to `VisitUpdate` in `app/schemas/visit.py`

## 3. Database

- [x] 3.1 Delete local `dental_ordination.db` and restart server to recreate with new column (or run `ALTER TABLE visits ADD COLUMN paid BOOLEAN DEFAULT 0`)
- [ ] 3.2 Run `ALTER TABLE visits ADD COLUMN paid BOOLEAN NOT NULL DEFAULT FALSE` on production PostgreSQL before deploying
