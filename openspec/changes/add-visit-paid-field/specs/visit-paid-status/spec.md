## ADDED Requirements

### Requirement: Visit has paid status
The Visit model SHALL include a `paid` boolean field that defaults to `False`. All visit API responses SHALL include the `paid` field.

#### Scenario: New visit defaults to unpaid
- **WHEN** a visit is created without specifying `paid`
- **THEN** the visit SHALL be saved with `paid=False`
- **AND** the response SHALL include `"paid": false`

#### Scenario: New visit created as paid
- **WHEN** a visit is created with `paid=true` in the request body
- **THEN** the visit SHALL be saved with `paid=True`
- **AND** the response SHALL include `"paid": true`

### Requirement: Visit paid status can be updated
Staff (admin or doctor) SHALL be able to update the `paid` field on an existing visit via the update endpoint.

#### Scenario: Mark visit as paid
- **WHEN** a PUT request is sent to `/api/visits/{id}` with `{"paid": true}`
- **THEN** the visit `paid` field SHALL be updated to `True`
- **AND** the response SHALL include `"paid": true`

#### Scenario: Mark visit as unpaid
- **WHEN** a PUT request is sent to `/api/visits/{id}` with `{"paid": false}`
- **THEN** the visit `paid` field SHALL be updated to `False`
- **AND** the response SHALL include `"paid": false`

#### Scenario: Update without paid field preserves current value
- **WHEN** a PUT request is sent to `/api/visits/{id}` without the `paid` field
- **THEN** the visit `paid` field SHALL remain unchanged

### Requirement: Existing visits default to unpaid
When the `paid` column is added to the database, all existing visit rows SHALL have `paid` set to `False`.

#### Scenario: Existing visit after migration
- **WHEN** the `paid` column is added to a table with existing visits
- **THEN** all existing visits SHALL have `paid=False`
