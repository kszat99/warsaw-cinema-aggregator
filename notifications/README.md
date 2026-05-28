# Movie Alert Notifications

This folder contains a Google Forms + Google Sheets + Apps Script notification backend for movie alerts.

The intended flow:

1. A user submits a Google Form with email + movie title.
2. Apps Script stores a pending alert in Google Sheets and sends a confirmation email.
3. The user confirms via email link.
4. A daily Apps Script job fetches the public `dist/showtimes.json`.
5. If an active one-time alert matches a movie title, Apps Script sends one notification email and marks the alert as `notified`.
6. If an active persistent alert finds newly detected screenings, Apps Script sends only the new screenings and keeps the alert `active`.

## 1. Create The Google Form

Create a Google Form with exactly these questions:

- `Email`
- `Film`
- `Alert type`
- `Format filter`

Keep all required. The Apps Script also recognizes Polish-ish variants, but these names are the least fussy.

Recommended `Alert type` multiple-choice options:

- `Persistent - email me when new screenings appear until I cancel`
- `One-time - email me once, then stop`

Recommended `Format filter` multiple-choice options:

- `Any screening format`
- `IMAX only`

In the form, go to **Responses** and create/link a Google Sheet.

## 2. Add The Apps Script

Open the linked Google Sheet.

Go to:

`Extensions -> Apps Script`

Replace the default file contents with:

`notifications/google-apps-script/Code.gs`

Run the `setup` function once from Apps Script.

Google will ask for permissions. Approve them.

## 3. Add The Form Submit Trigger

In Apps Script, open **Triggers**.

Create a trigger:

- Function: `onFormSubmit`
- Event source: `From spreadsheet`
- Event type: `On form submit`

## 4. Deploy The Confirm/Cancel Web App

In Apps Script:

`Deploy -> New deployment`

Choose:

- Type: `Web app`
- Execute as: `Me`
- Who has access: `Anyone`

Deploy it.

This gives confirmation/cancel links like:

`https://script.google.com/macros/s/.../exec?action=confirm&token=...`

## 5. Add The Daily Alert Checker

In Apps Script, add another trigger:

- Function: `runAlertCheck`
- Event source: `Time-driven`
- Type: `Day timer`
- Time: after your scraper usually updates the site

For example, if your local PC updates around morning login, run this around noon.

## 6. Test It

1. Submit the form with your own email and a movie currently present on the site.
2. Confirm the alert via email.
3. In Apps Script, manually run `runAlertCheck`.
4. A one-time alert should send one notification email and change from `active` to `notified`.
5. A persistent alert should send an email only when new screening keys appear, then remain `active`.

## Sheet Statuses

- `pending`: form submitted, email not confirmed yet
- `active`: confirmed and waiting for a match
- `notified`: one-time alert matched and emailed once
- `cancelled`: user cancelled

## Notes

- `alert_type` is `one_time` or `persistent`.
- `format_filter` is `any` or `imax`.
- Persistent alerts store `reported_screening_keys`, so the same screening is not emailed every day.
- The matching logic is simple and deterministic. It normalizes titles, then checks whether the alert query and screening title contain each other.
- If matching is too loose or too strict, update `normalizeTitle_` and `findMatches_` in `Code.gs`.
- Apps Script/Gmail quotas apply, but they should be fine for a small public utility.
