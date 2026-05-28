const CONFIG = {
  SHEET_NAME: 'Alerts',
  SHOWTIMES_URL: 'https://kszat99.github.io/warsaw-cinema-aggregator/dist/showtimes.json',
  SITE_URL: 'https://kszat99.github.io/warsaw-cinema-aggregator/',
  WEB_APP_URL: 'https://script.google.com/macros/s/AKfycbxIK95ObG84btroQNgjJzkWzG6HEAjg2zbDttXwnOgKpuhwZCMFlftKHNA828IPr-7T/exec',
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
  'alert_type',
  'format_filter',
  'reported_screening_keys',
  'last_checked_at',
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
  const alertType = values.alertType;
  const formatFilter = values.formatFilter;

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
    alertType,
    formatFilter,
    '',
    '',
  ]);

  sendConfirmationEmail_(email, queryRaw, confirmToken, cancelToken, alertType, formatFilter);
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

    const alertType = getAlertType_(row);
    const formatFilter = getFormatFilter_(row);
    const matches = findMatches_(row.query_norm, screenings, formatFilter);
    const now = new Date().toISOString();

    sheet.getRange(row.rowNumber, columnIndex_('last_checked_at')).setValue(now);

    if (matches.length === 0) {
      return;
    }

    if (alertType === 'persistent') {
      const reportedKeys = parseJsonArray_(row.reported_screening_keys);
      const reportedSet = new Set(reportedKeys);
      const newMatches = matches.filter((match) => !reportedSet.has(screeningKey_(match)));

      if (newMatches.length === 0) {
        return;
      }

      sendMatchEmail_(row.email, row.query_raw, newMatches, row.cancel_token, {
        alertType,
        formatFilter,
      });

      const nextKeys = Array.from(new Set(reportedKeys.concat(newMatches.map(screeningKey_))));
      const matchedTitle = newMatches[0].title_raw || newMatches[0].title_norm;
      sheet.getRange(row.rowNumber, columnIndex_('notified_at')).setValue(now);
      sheet.getRange(row.rowNumber, columnIndex_('matched_title')).setValue(matchedTitle);
      sheet
        .getRange(row.rowNumber, columnIndex_('matched_screenings_json'))
        .setValue(JSON.stringify(newMatches.slice(0, CONFIG.MAX_SCREENINGS_IN_EMAIL)));
      sheet.getRange(row.rowNumber, columnIndex_('reported_screening_keys')).setValue(JSON.stringify(nextKeys));
      return;
    }

    sendMatchEmail_(row.email, row.query_raw, matches, row.cancel_token, {
      alertType,
      formatFilter,
    });

    const matchedTitle = matches[0].title_raw || matches[0].title_norm;
    sheet.getRange(row.rowNumber, columnIndex_('status')).setValue('notified');
    sheet.getRange(row.rowNumber, columnIndex_('notified_at')).setValue(now);
    sheet.getRange(row.rowNumber, columnIndex_('matched_title')).setValue(matchedTitle);
    sheet
      .getRange(row.rowNumber, columnIndex_('matched_screenings_json'))
      .setValue(JSON.stringify(matches.slice(0, CONFIG.MAX_SCREENINGS_IN_EMAIL)));
    sheet.getRange(row.rowNumber, columnIndex_('reported_screening_keys')).setValue(JSON.stringify(matches.map(screeningKey_)));
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

  const alertType = getAlertType_(row);
  const formatFilter = getFormatFilter_(row);
  if (alertType === 'persistent') {
    return html_(`Alert confirmed. You will get emails when new${formatFilter === 'imax' ? ' IMAX' : ''} screenings appear until you cancel it.`);
  }

  return html_(`Alert confirmed. You will get one email when this movie${formatFilter === 'imax' ? ' has IMAX screenings' : ' appears'}.`);
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

function findMatches_(queryNorm, screenings, formatFilter) {
  const byMovie = {};

  screenings.forEach((screening) => {
    if (!matchesFormatFilter_(screening, formatFilter)) {
      return;
    }

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
    .sort((a, b) => String(a.starts_at).localeCompare(String(b.starts_at)));
}

function sendConfirmationEmail_(email, queryRaw, confirmToken, cancelToken, alertType, formatFilter) {
  const baseUrl = getWebAppUrl_();
  const confirmUrl = `${baseUrl}?action=confirm&token=${encodeURIComponent(confirmToken)}`;
  const cancelUrl = `${baseUrl}?action=cancel&token=${encodeURIComponent(cancelToken)}`;
  const subject = `Warsaw Cinemas Screenings Aggregator - Confirm your ${queryRaw} Movie Alert`;
  const alertTypeLabel = formatAlertTypeLabel_(alertType);
  const formatFilterLabel = formatFilterLabel_(formatFilter);

  const body = [
    'Warsaw Cinemas Screenings Aggregator',
    '',
    `Confirm your movie alert for: "${queryRaw}"`,
    '',
    `Alert type: ${alertTypeLabel}`,
    `Screenings: ${formatFilterLabel}`,
    '',
    alertType === 'persistent'
      ? 'We will email you whenever new matching screenings appear, until you cancel the alert.'
      : 'We will send one email when this movie first appears in Warsaw cinemas.',
    '',
    'Confirm alert:',
    confirmUrl,
    '',
    "If this wasn't you, you can ignore this email or cancel the alert:",
    cancelUrl,
  ].join('\n');

  MailApp.sendEmail({
    to: email,
    subject,
    body,
    htmlBody: buildConfirmationHtml_(queryRaw, confirmUrl, cancelUrl, alertType, formatFilter),
  });
}

function sendMatchEmail_(email, queryRaw, matches, cancelToken, options) {
  const alertType = options && options.alertType ? options.alertType : 'one_time';
  const formatFilter = options && options.formatFilter ? options.formatFilter : 'any';
  const cancelUrl = `${getWebAppUrl_()}?action=cancel&token=${encodeURIComponent(cancelToken)}`;
  const appUrl = buildAggregatorUrl_(queryRaw);
  const summary = buildMatchSummary_(matches);
  const subject = alertType === 'persistent'
    ? `Warsaw Cinemas Screenings Aggregator - new ${queryRaw} screenings in Warsaw :)`
    : `Warsaw Cinemas Screenings Aggregator - ${queryRaw} is now screening in Warsaw :)`;
  const title = matches[0].title_raw || queryRaw;
  const lines = buildPlainTextMatchLines_(summary);
  const openingLine = alertType === 'persistent'
    ? `Good news. New${formatFilter === 'imax' ? ' IMAX' : ''} screenings matched your "${queryRaw}" alert.`
    : `Good news. "${queryRaw}" is now screening in Warsaw.`;
  const screeningLabel = alertType === 'persistent' ? 'new screenings' : 'screenings';
  const footerLine = alertType === 'persistent'
    ? 'This is a persistent alert. You will only receive future emails when new matching screenings appear. To stop receiving emails for this alert, use the cancel link below.'
    : 'This was a one-time alert, so you will not receive more emails for it.';

  const body = [
    'Warsaw Cinemas Screenings Aggregator',
    '',
    openingLine,
    '',
    `Found ${summary.totalScreenings} ${screeningLabel} across ${summary.totalCinemas} cinemas and ${summary.totalDays} days.`,
    `Earliest screening: ${formatDateTimeText_(summary.earliest.starts_at)}.`,
    '',
    'Earliest days:',
    ...lines,
    '',
    `Open all matching screenings: ${appUrl}`,
    '',
    footerLine,
    `Cancel link: ${cancelUrl}`,
  ].join('\n');

  MailApp.sendEmail({
    to: email,
    subject,
    body,
    htmlBody: buildMatchHtml_(queryRaw, title, summary, appUrl, cancelUrl, alertType, formatFilter),
  });
}

function buildConfirmationHtml_(queryRaw, confirmUrl, cancelUrl, alertType, formatFilter) {
  const alertTypeLabel = formatAlertTypeLabel_(alertType);
  const formatFilterLabel = formatFilterLabel_(formatFilter);
  const explanation = alertType === 'persistent'
    ? 'We will email you whenever new matching screenings appear, until you cancel the alert.'
    : 'We will send one email when this movie first appears in Warsaw cinemas.';

  return emailShell_(`
    <h1 style="margin:0 0 12px;font-size:24px;line-height:1.25;color:#f8fafc;">Confirm your movie alert</h1>
    <p style="margin:0 0 18px;color:#cbd5e1;font-size:15px;line-height:1.6;">
      ${escapeHtml_(explanation)}
    </p>
    <div style="margin:0 0 22px;padding:16px;border:1px solid rgba(255,255,255,0.12);border-radius:12px;background:#0f172a;">
      <div style="font-size:13px;color:#94a3b8;margin-bottom:6px;">Movie alert</div>
      <div style="font-size:22px;font-weight:700;color:#f8fafc;">${escapeHtml_(queryRaw)}</div>
      <div style="margin-top:10px;color:#cbd5e1;font-size:14px;line-height:1.5;">
        ${escapeHtml_(alertTypeLabel)} · ${escapeHtml_(formatFilterLabel)}
      </div>
    </div>
    ${buttonHtml_(confirmUrl, 'Confirm alert')}
    <p style="margin:22px 0 0;color:#94a3b8;font-size:13px;line-height:1.6;">
      No account needed. If this was not you, you can ignore this email
      or <a href="${cancelUrl}" style="color:#67e8f9;">cancel the alert</a>.
    </p>
  `);
}

function buildMatchHtml_(queryRaw, title, summary, appUrl, cancelUrl, alertType, formatFilter) {
  const posterHtml = summary.posterUrl
    ? `<td style="width:96px;padding:0 18px 18px 0;vertical-align:top;">
         <img src="${summary.posterUrl}" alt="${escapeHtml_(title)} poster" width="96" style="display:block;width:96px;border-radius:8px;border:1px solid rgba(255,255,255,0.12);">
       </td>`
    : '';
  const dayHtml = summary.days.map(buildDayHtml_).join('');
  const headline = alertType === 'persistent'
    ? `New${formatFilter === 'imax' ? ' IMAX' : ''} screenings for "${queryRaw}"`
    : `Good news - "${queryRaw}" is screening.`;
  const footerLine = alertType === 'persistent'
    ? 'This is a persistent alert. Future emails will include only newly detected matching screenings. To stop receiving emails for this alert, use the cancel link below.'
    : 'This was a one-time alert, so you will not receive more emails for it.';
  const screeningLabel = alertType === 'persistent' ? 'new screenings' : 'screenings';

  return emailShell_(`
    <h1 style="margin:0 0 12px;font-size:24px;line-height:1.25;color:#f8fafc;">${escapeHtml_(headline)}</h1>
    <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;margin:0 0 18px;">
      <tr>
        ${posterHtml}
        <td style="vertical-align:top;padding:0 0 18px;">
          <p style="margin:0 0 8px;color:#cbd5e1;font-size:15px;line-height:1.6;">
            Found <strong style="color:#f8fafc;">${summary.totalScreenings}</strong> ${escapeHtml_(screeningLabel)} across
            <strong style="color:#f8fafc;">${summary.totalCinemas}</strong> cinemas and
            <strong style="color:#f8fafc;">${summary.totalDays}</strong> days.
          </p>
          <p style="margin:0;color:#94a3b8;font-size:14px;line-height:1.5;">
            Earliest screening: ${escapeHtml_(formatDateTimeText_(summary.earliest.starts_at))}
          </p>
        </td>
      </tr>
    </table>
    <h2 style="margin:4px 0 12px;font-size:17px;color:#f8fafc;">Earliest days</h2>
    ${dayHtml}
    ${buttonHtml_(appUrl, 'View all matching screenings')}
    <p style="margin:22px 0 0;color:#94a3b8;font-size:13px;line-height:1.6;">
      ${escapeHtml_(footerLine)}
      <a href="${cancelUrl}" style="color:#67e8f9;">Cancel alert</a>
    </p>
  `);
}

function buildMatchSummary_(matches) {
  const sorted = matches.slice().sort((a, b) => String(a.starts_at).localeCompare(String(b.starts_at)));
  const cinemaNames = new Set(sorted.map((screening) => screening.cinema_name).filter(Boolean));
  const dayKeys = new Set(sorted.map((screening) => getDayKey_(screening.starts_at)).filter(Boolean));
  const dayMap = {};

  sorted.forEach((screening) => {
    const dayKey = getDayKey_(screening.starts_at);
    if (!dayKey) {
      return;
    }
    if (!dayMap[dayKey]) {
      dayMap[dayKey] = [];
    }
    dayMap[dayKey].push(screening);
  });

  const days = Object.keys(dayMap)
    .sort()
    .slice(0, 3)
    .map((dayKey) => ({
      dayKey,
      label: formatDayLabel_(dayKey),
      total: dayMap[dayKey].length,
      cinemas: groupDayByCinema_(dayMap[dayKey]),
    }));

  return {
    totalScreenings: sorted.length,
    totalCinemas: cinemaNames.size,
    totalDays: dayKeys.size,
    earliest: sorted[0],
    posterUrl: (sorted.find((screening) => screening.poster_url) || {}).poster_url || '',
    days,
  };
}

function groupDayByCinema_(screenings) {
  const byCinema = {};
  screenings.forEach((screening) => {
    const cinema = screening.cinema_name || 'Unknown cinema';
    if (!byCinema[cinema]) {
      byCinema[cinema] = [];
    }
    byCinema[cinema].push(screening);
  });

  return Object.keys(byCinema).sort().map((cinemaName) => ({
    cinemaName,
    screenings: byCinema[cinemaName].sort((a, b) => String(a.starts_at).localeCompare(String(b.starts_at))),
  }));
}

function buildDayHtml_(day) {
  const cinemaRows = day.cinemas.map((cinema) => {
    const timeLinks = cinema.screenings.map((screening) => {
      const time = escapeHtml_(formatTime_(screening.starts_at));
      const href = screening.booking_url || CONFIG.SITE_URL;
      return `<a href="${href}" style="display:inline-block;margin:0 6px 6px 0;color:#f8fafc;text-decoration:none;background:#1e293b;border:1px solid rgba(255,255,255,0.12);border-radius:999px;padding:5px 9px;font-size:13px;">${time}</a>`;
    }).join('');
    return `
      <tr>
        <td style="padding:8px 0 2px;color:#67e8f9;font-weight:700;font-size:14px;">${escapeHtml_(cinema.cinemaName)}</td>
      </tr>
      <tr>
        <td style="padding:0 0 8px;">${timeLinks}</td>
      </tr>
    `;
  }).join('');

  return `
    <div style="margin:0 0 14px;padding:14px;border:1px solid rgba(255,255,255,0.10);border-radius:12px;background:#0f172a;">
      <div style="margin:0 0 6px;color:#f8fafc;font-weight:800;font-size:15px;">
        ${escapeHtml_(day.label)} - ${day.total} screenings
      </div>
      <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;">
        ${cinemaRows}
      </table>
    </div>
  `;
}

function buildPlainTextMatchLines_(summary) {
  const lines = [];
  summary.days.forEach((day) => {
    lines.push('');
    lines.push(`${day.label} - ${day.total} screenings`);
    day.cinemas.forEach((cinema) => {
      const times = cinema.screenings.map((screening) => formatTime_(screening.starts_at)).join(' · ');
      lines.push(`${cinema.cinemaName} - ${times}`);
    });
  });
  return lines;
}

function emailShell_(contentHtml) {
  return `
    <div style="margin:0;padding:0;background:#020617;color:#f8fafc;font-family:Arial,Helvetica,sans-serif;">
      <div style="max-width:640px;margin:0 auto;padding:28px 16px;">
        <div style="margin:0 0 16px;font-size:14px;font-weight:800;color:#67e8f9;letter-spacing:0.02em;">
          Warsaw Cinemas Screenings Aggregator
        </div>
        <div style="border:1px solid rgba(255,255,255,0.12);border-radius:16px;background:#111827;padding:24px;box-shadow:0 16px 40px rgba(0,0,0,0.35);">
          ${contentHtml}
        </div>
        <p style="margin:16px 0 0;color:#64748b;font-size:12px;line-height:1.5;">
          This email was sent by Warsaw Cinemas Screenings Aggregator because a movie alert was created with this address.
        </p>
      </div>
    </div>
  `;
}

function buttonHtml_(url, label) {
  return `<a href="${url}" style="display:inline-block;background:#8b5cf6;color:#ffffff;text-decoration:none;border-radius:999px;padding:12px 18px;font-weight:800;font-size:14px;">${escapeHtml_(label)}</a>`;
}

function getAlertType_(row) {
  return normalizeAlertType_(row.alert_type || 'one_time');
}

function getFormatFilter_(row) {
  return normalizeFormatFilter_(row.format_filter || 'any');
}

function normalizeAlertType_(value) {
  const normalized = normalizeFieldName_(value);
  if (
    normalized.includes('persistent')
    || normalized.includes('forever')
    || normalized.includes('manual')
    || normalized.includes('until cancel')
    || normalized.includes('new screenings')
    || normalized.includes('nowe seanse')
    || normalized.includes('stale')
  ) {
    return 'persistent';
  }
  return 'one_time';
}

function normalizeFormatFilter_(value) {
  const normalized = normalizeFieldName_(value);
  if (normalized.includes('imax')) {
    return 'imax';
  }
  return 'any';
}

function formatAlertTypeLabel_(alertType) {
  return alertType === 'persistent' ? 'Persistent alert' : 'One-time alert';
}

function formatFilterLabel_(formatFilter) {
  return formatFilter === 'imax' ? 'IMAX screenings only' : 'Any screening format';
}

function matchesFormatFilter_(screening, formatFilter) {
  if (formatFilter !== 'imax') {
    return true;
  }

  const values = []
    .concat(screening.tags || [])
    .concat([
      screening.format,
      screening.cinema_name,
      screening.title_raw,
      screening.title_norm,
    ])
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());

  return values.some((value) => value.includes('imax'));
}

function screeningKey_(screening) {
  const tags = Array.isArray(screening.tags) ? screening.tags.slice().sort().join(',') : '';
  return [
    screening.cinema_id || '',
    screening.cinema_name || '',
    normalizeTitle_(screening.title_norm || screening.title_raw || ''),
    screening.starts_at || '',
    tags,
  ].join('|');
}

function parseJsonArray_(value) {
  if (!value) {
    return [];
  }

  try {
    const parsed = JSON.parse(String(value));
    return Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : [];
  } catch (error) {
    return [];
  }
}

function buildAggregatorUrl_(queryRaw) {
  return `${CONFIG.SITE_URL}?q=${encodeURIComponent(queryRaw)}&all=1`;
}

function getDayKey_(startsAt) {
  return String(startsAt || '').slice(0, 10);
}

function formatDayLabel_(dayKey) {
  const parts = String(dayKey).split('-');
  if (parts.length !== 3) {
    return dayKey;
  }
  return `${parts[2]}/${parts[1]}`;
}

function formatTime_(startsAt) {
  return String(startsAt || '').replace('T', ' ').slice(11, 16);
}

function formatDateTimeText_(startsAt) {
  const value = String(startsAt || '');
  const day = formatDayLabel_(value.slice(0, 10));
  const time = formatTime_(value);
  return `${day} at ${time}`;
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
  let alertType = 'one_time';
  let formatFilter = 'any';

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

  const alertTypeEntry = entries.find((entry) =>
    entry.keyNorm.includes('alert type')
    || entry.keyNorm.includes('notification type')
    || entry.keyNorm.includes('typ alertu')
    || entry.keyNorm.includes('rodzaj alertu')
  );
  if (alertTypeEntry) {
    alertType = normalizeAlertType_(alertTypeEntry.value);
  }

  const formatFilterEntry = entries.find((entry) =>
    entry.keyNorm.includes('format')
    || entry.keyNorm.includes('imax')
    || entry.keyNorm.includes('screening type')
    || entry.keyNorm.includes('typ seansu')
  );
  if (formatFilterEntry) {
    formatFilter = normalizeFormatFilter_(formatFilterEntry.value);
  }

  return {
    email,
    query,
    alertType,
    formatFilter,
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
