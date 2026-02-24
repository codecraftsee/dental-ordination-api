## ADDED Requirements

### Requirement: Delete all visits
The system SHALL hard-delete all visit records when `DELETE /api/admin/visits` is called by an admin.

#### Scenario: Admin deletes all visits
- **WHEN** an admin sends `DELETE /api/admin/visits`
- **THEN** all visit records are permanently removed and the response returns `{ "deleted": <count> }`

#### Scenario: Unauthenticated request is rejected
- **WHEN** a non-admin or unauthenticated user sends `DELETE /api/admin/visits`
- **THEN** the system returns `401` or `403`

---

### Requirement: Delete all patients
The system SHALL hard-delete all patient records (and cascade to their visits) when `DELETE /api/admin/patients` is called by an admin.

#### Scenario: Admin deletes all patients
- **WHEN** an admin sends `DELETE /api/admin/patients`
- **THEN** all patient records and their associated visits are permanently removed and the response returns `{ "deleted": <count> }`

#### Scenario: Unauthenticated request is rejected
- **WHEN** a non-admin or unauthenticated user sends `DELETE /api/admin/patients`
- **THEN** the system returns `401` or `403`

---

### Requirement: Delete all doctors
The system SHALL hard-delete all doctor records when `DELETE /api/admin/doctors` is called by an admin.

#### Scenario: Admin deletes all doctors
- **WHEN** an admin sends `DELETE /api/admin/doctors`
- **THEN** all doctor records are permanently removed and the response returns `{ "deleted": <count> }`

#### Scenario: Unauthenticated request is rejected
- **WHEN** a non-admin or unauthenticated user sends `DELETE /api/admin/doctors`
- **THEN** the system returns `401` or `403`

---

### Requirement: Delete all diagnoses
The system SHALL hard-delete all diagnosis records when `DELETE /api/admin/diagnoses` is called by an admin.

#### Scenario: Admin deletes all diagnoses
- **WHEN** an admin sends `DELETE /api/admin/diagnoses`
- **THEN** all diagnosis records are permanently removed and the response returns `{ "deleted": <count> }`

#### Scenario: Unauthenticated request is rejected
- **WHEN** a non-admin or unauthenticated user sends `DELETE /api/admin/diagnoses`
- **THEN** the system returns `401` or `403`

---

### Requirement: Delete all treatments
The system SHALL hard-delete all treatment records when `DELETE /api/admin/treatments` is called by an admin.

#### Scenario: Admin deletes all treatments
- **WHEN** an admin sends `DELETE /api/admin/treatments`
- **THEN** all treatment records are permanently removed and the response returns `{ "deleted": <count> }`

#### Scenario: Unauthenticated request is rejected
- **WHEN** a non-admin or unauthenticated user sends `DELETE /api/admin/treatments`
- **THEN** the system returns `401` or `403`

---

### Requirement: Delete all data
The system SHALL hard-delete all data in FK-safe cascade order when `DELETE /api/admin/all` is called by an admin.

#### Scenario: Admin deletes all data
- **WHEN** an admin sends `DELETE /api/admin/all`
- **THEN** records are deleted in order: visits → patients → doctors → diagnoses → treatments, and the response returns counts per entity

#### Scenario: Deletion is atomic
- **WHEN** an error occurs mid-deletion in `DELETE /api/admin/all`
- **THEN** the entire operation is rolled back and no partial data is deleted

#### Scenario: Unauthenticated request is rejected
- **WHEN** a non-admin or unauthenticated user sends `DELETE /api/admin/all`
- **THEN** the system returns `401` or `403`
