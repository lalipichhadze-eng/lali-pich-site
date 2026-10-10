// Lead forms (replace Elementor Pro forms). Later lane: set the CRM endpoint on the next line, nothing else.
const SUBMIT_URL = null; // e.g. 'https://crm.example/api/lead'  (null = no CRM yet, redirect only)

document.querySelectorAll('form.lp-form').forEach(function (form) {
  var q = new URLSearchParams(location.search);
  ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'].forEach(function (k) {
    var f = form.querySelector('[name="form_fields[' + k + ']"]');
    if (f && q.get(k)) f.value = q.get(k);
  });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var d = {};
    new FormData(form).forEach(function (v, k) { d[k.replace(/^form_fields\[(.*)\]$/, '$1')] = v; });
    var go = function () {
      var url = form.dataset.redirect;
      if (!url) return;
      var u = new URL(url);
      if (u.hostname.indexOf('calendly.com') > -1) { // Calendly prefill
        u.searchParams.set('name', ((d.first_name || '') + ' ' + (d.last_name || '')).trim());
        if (d.email) u.searchParams.set('email', d.email);
      }
      location.href = u.toString();
    };
    if (!SUBMIT_URL) return go();
    fetch(SUBMIT_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d), keepalive: true })
      .catch(function () {}).then(go);
  });
});
