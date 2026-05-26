const CONFIG = {
  SHEET_NAME: 'Alerts',
  SHOWTIMES_URL: 'https://kszat99.github.io/warsaw-cinema-aggregator/dist/showtimes.json',
  SITE_URL: 'https://kszat99.github.io/warsaw-cinema-aggregator/',
  WEB_APP_URL: 'https://script.google.com/macros/s/AKfycby35k6nVB_cBXaloi56XPQQOKeNUuDV2pTuRcXgq2HmBztXt8XbNHFJMYxuVkXvWY_d/exec',
  MAX_SCREENINGS_IN_EMAIL: 12,
  MIN_QUERY_LENGTH: 4,
};

const COLUMNS = [
  'timestamp',
  'email',
  'query_raw',
  'query_norm',
  'status',
  'confirm_token',
  'cancel_token',
  'created_at',
  'confirmed_at',
  'notified_at',
  'matched_title',
  'matched_screenings_json',
];

function setup() {
  const sheet = getSheet_();
  ensureHeader_(sheet);
}

function onFormSubmit(e) {
  const sheet = getSheet_();
  ensureHeader_(sheet);

  const values = getFormValues_(e);
  console.log(`Form submit parsed as email="${values.email}", query="${values.query}"`);
  const email = values.email;
  const queryRaw = values.query;
  const queryNorm = normalizeTitle_(queryRaw);

  if (!email || !queryRaw || queryNorm.length < CONFIG.MIN_QUERY_LENGTH) {
    console.log(`Skipping form response. namedValues=${JSON.stringify(e && e.namedValues ? e.namedValues : {})}`);
    return;
  }

  const now = new Date().toISOString();
  const confirmToken = makeToken_();
  const cancelToken = makeToken_();

  sheet.appendRow([
    now,
    email,
    queryRaw,
    queryNorm,
    'pending',
    confirmToken,
    cancelToken,
    now,
    '',
    '',
    '',
    '',
  ]);

  sendConfirmationEmail_(email, queryRaw, confirmToken, cancelToken);
}

function doGet(e) {
  const action = e.parameter.action;
  const token = e.parameter.token;

  if (!action || !token) {
    return html_('Invalid link.');
  }

  if (action === 'confirm') {
    return confirmAlert_(token);
  }

  if (action === 'cancel') {
    return cancelAlert_(token);
  }

  return html_('Unknown action.');
}

function runAlertCheck() {
  const sheet = getSheet_();
  ensureHeader_(sheet);

  const rows = getRows_(sheet);
  const response = UrlFetchApp.fetch(`${CONFIG.SHOWTIMES_URL}?v=${Date.now()}`, {
    muteHttpExceptions: true,
  });

  if (response.getResponseCode() !== 200) {
    throw new Error(`Could not fetch showtimes: ${response.getResponseCode()}`);
  }

  const payload = JSON.parse(response.getContentText());
  const screenings = payload.screenings || [];

  rows.forEach((row) => {
    if (row.status !== 'active') {
      return;
    }

    const matches = findMatches_(row.query_norm, screenings);
    if (matches.length === 0) {
      return;
    }

    sendMatchEmail_(row.email, row.query_raw, matches, row.cancel_token);

    const matchedTitle = matches[0].title_raw || matches[0].title_norm;
    sheet.getRange(row.rowNumber, columnIndex_('status')).setValue('notified');
    sheet.getRange(row.rowNumber, columnIndex_('notified_at')).setValue(new Date().toISOString());
    sheet.getRange(row.rowNumber, columnIndex_('matched_title')).setValue(matchedTitle);
    sheet
      .getRange(row.rowNumber, columnIndex_('matched_screenings_json'))
      .setValue(JSON.stringify(matches.slice(0, CONFIG.MAX_SCREENINGS_IN_EMAIL)));
  });
}

function confirmAlert_(token) {
  const sheet = getSheet_();
  const rows = getRows_(sheet);
  const row = rows.find((candidate) => candidate.confirm_token === token);

  if (!row) {
    return html_('Confirmation link not found.');
  }

  if (row.status === 'pending') {
    sheet.getRange(row.rowNumber, columnIndex_('status')).setValue('active');
    sheet.getRange(row.rowNumber, columnIndex_('confirmed_at')).setValue(new Date().toISOString());
  }

  return html_('Alert confirmed. You will get one email when this movie appears.');
}

function cancelAlert_(token) {
  const sheet = getSheet_();
  const rows = getRows_(sheet);
  const row = rows.find((candidate) => candidate.cancel_token === token);

  if (!row) {
    return html_('Cancel link not found.');
  }

  sheet.getRange(row.rowNumber, columnIndex_('status')).setValue('cancelled');
  return html_('Alert cancelled.');
}

function findMatches_(queryNorm, screenings) {
  const byMovie = {};

  screenings.forEach((screening) => {
    const titleNorm = normalizeTitle_(screening.title_norm || screening.title_raw || '');
    if (!titleNorm) {
      return;
    }

    const isMatch = titleNorm.includes(queryNorm) || queryNorm.includes(titleNorm);
    if (!isMatch) {
      return;
    }

    if (!byMovie[titleNorm]) {
      byMovie[titleNorm] = [];
    }
    byMovie[titleNorm].push(screening);
  });

  const bestTitle = Object.keys(byMovie).sort((a, b) => byMovie[b].length - byMovie[a].length)[0];
  if (!bestTitle) {
    return [];
  }

  return byMovie[bestTitle]
    .sort((a, b) => String(a.starts_at).localeCompare(String(b.starts_at)))
    .slice(0, CONFIG.MAX_SCREENINGS_IN_EMAIL);
}

function sendConfirmationEmail_(email, queryRaw, confirmToken, cancelToken) {
  const baseUrl = getWebAppUrl_();
  const confirmUrl = `${baseUrl}?action=confirm&token=${encodeURIComponent(confirmToken)}`;
  const cancelUrl = `${baseUrl}?action=cancel&token=${encodeURIComponent(cancelToken)}`;

  const body = [
    `Confirm your Warsaw cinema alert for: "${queryRaw}"`,
    '',
    'Click to confirm:',
    confirmUrl,
    '',
    "If this wasn't you, ignore this email or cancel it here:",
    cancelUrl,
  ].join('\n');

  MailApp.sendEmail({
    to: email,
    subject: `Confirm cinema alert: ${queryRaw}`,
    body,
  });
}

function sendMatchEmail_(email, queryRaw, matches, cancelToken) {
  const cancelUrl = `${getWebAppUrl_()}?action=cancel&token=${encodeURIComponent(cancelToken)}`;
  const lines = matches.map((screening) => {
    const date = String(screening.starts_at || '').replace('T', ' ').slice(0, 16);
    const tags = screening.tags && screening.tags.length ? ` (${screening.tags.join(', ')})` : '';
    return `- ${date} | ${screening.cinema_name} | ${screening.title_raw}${tags}`;
  });

  const body = [
    `Good news. "${queryRaw}" is now screening in Warsaw.`,
    '',
    'Earliest matching screenings:',
    ...lines,
    '',
    `Open the cinema aggregator: ${CONFIG.SITE_URL}`,
    '',
    'This was a one-time alert, so you will not receive more emails for it.',
    `Cancel link: ${cancelUrl}`,
  ].join('\n');

  MailApp.sendEmail({
    to: email,
    subject: `Cinema alert: ${queryRaw} is screening`,
    body,
  });
}

function normalizeTitle_(title) {
  if (!title) {
    return '';
  }

  let value = String(title)
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');

  value = value
    .replace(/&amp;/g, ' i ')
    .replace(/\s*&\s*/g, ' i ')
    .replace(/\band\b/g, 'i')
    .replace(/^gwiezdne wojny\s+/, '')
    .replace(/\s+-\s+(napisy|dubbing|lektor).*$/g, '')
    .replace(/\s+(napisy|dubbing|lektor|2d|3d|imax)$/g, '')
    .replace(/\bii\b/g, '2')
    .replace(/\biii\b/g, '3')
    .replace(/\biv\b/g, '4')
    .replace(/\bv\b/g, '5')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  return value;
}

function getFormValues_(e) {
  const named = e && e.namedValues ? e.namedValues : {};
  const entries = Object.keys(named).map((key) => ({
    key,
    keyNorm: normalizeFieldName_(key),
    value: firstValue_(named[key]),
  }));

  let email = '';
  let query = '';

  const emailEntry = entries.find((entry) =>
    entry.keyNorm.includes('email')
    || entry.keyNorm.includes('mail')
    || entry.keyNorm.includes('adres e mail')
  );
  if (emailEntry) {
    email = emailEntry.value;
  }

  if (!email) {
    const emailValueEntry = entries.find((entry) => /[^@\s]+@[^@\s]+\.[^@\s]+/.test(entry.value));
    if (emailValueEntry) {
      email = emailValueEntry.value;
    }
  }

  const queryEntry = entries.find((entry) =>
    entry.keyNorm === 'film'
    || entry.keyNorm.includes('film')
    || entry.keyNorm.includes('movie')
    || entry.keyNorm.includes('tytul')
    || entry.keyNorm.includes('title')
  );
  if (queryEntry) {
    query = queryEntry.value;
  }

  if (!query) {
    const fallbackEntry = entries.find((entry) =>
      entry.value
      && entry.value !== email
      && !/[^@\s]+@[^@\s]+\.[^@\s]+/.test(entry.value)
      && !entry.keyNorm.includes('timestamp')
      && !entry.keyNorm.includes('sygnatura')
    );
    if (fallbackEntry) {
      query = fallbackEntry.value;
    }
  }

  return {
    email,
    query,
  };
}

function normalizeFieldName_(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function firstValue_(value) {
  if (Array.isArray(value)) {
    return String(value[0] || '').trim();
  }
  return String(value || '').trim();
}

function getSheet_() {
  return SpreadsheetApp.getActive().getSheetByName(CONFIG.SHEET_NAME)
    || SpreadsheetApp.getActive().insertSheet(CONFIG.SHEET_NAME);
}

function ensureHeader_(sheet) {
  const current = sheet.getRange(1, 1, 1, COLUMNS.length).getValues()[0];
  const needsHeader = COLUMNS.some((name, index) => current[index] !== name);
  if (needsHeader) {
    sheet.getRange(1, 1, 1, COLUMNS.length).setValues([COLUMNS]);
  }
}

function getRows_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return [];
  }

  const values = sheet.getRange(2, 1, lastRow - 1, COLUMNS.length).getValues();
  return values.map((row, index) => {
    const record = { rowNumber: index + 2 };
    COLUMNS.forEach((column, columnIndex) => {
      record[column] = row[columnIndex];
    });
    return record;
  });
}

function columnIndex_(name) {
  return COLUMNS.indexOf(name) + 1;
}

function makeToken_() {
  return Utilities.getUuid() + '-' + Utilities.getUuid();
}

function getWebAppUrl_() {
  return CONFIG.WEB_APP_URL || ScriptApp.getService().getUrl();
}

function html_(message) {
  return HtmlService.createHtmlOutput(`<p>${escapeHtml_(message)}</p>`);
}

function escapeHtml_(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
