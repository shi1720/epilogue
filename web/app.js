/* Epilogue: same-origin API, private sessions, accessible dialogs, no build step. */
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
let state = null, meta = {}, user = null, feed = null, firebaseAuth = null, authSDK = null;
let refreshing = false, requestBusy = false, seenError = null, decisionSignature = '', timelineSignature = '', matterSignature = '';
let accessCode = '', noticeTimer, refreshTimer;
const seenActivity = new Set();
const busy = () => requestBusy || (state && state.status !== 'idle');
const money = (n) => '$' + Number(n || 0).toFixed(2);
const fmtDate = (iso) => iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-US', {month:'short', day:'numeric'}) : '';

async function api(path, data) {
  let response;
  try {
    response = await fetch(path, {credentials:'same-origin', cache:'no-store', ...(data !== undefined ? {
      method:'POST', headers:{'Content-Type':'application/json','X-Epilogue-Request':'1', ...(accessCode ? {'X-Epilogue-Code':accessCode} : {})}, body:JSON.stringify(data)
    } : {}), signal:AbortSignal.timeout(30000)});
  } catch { throw new Error('We could not reach Epilogue. Check your connection and try again.'); }
  let payload;
  try { payload = await response.json(); } catch { throw new Error('The service is waking up. Please try again in a moment.'); }
  if (!response.ok) {
    const error = new Error(typeof payload.detail === 'string' ? payload.detail : 'Please check your input and try again.');
    error.status = response.status;
    throw error;
  }
  return payload;
}

function notify(text) { $('notice').textContent = text; $('notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 7000); }
function showError(error, retry = false) {
  $('error-title').textContent = retry ? 'Your progress is saved.' : 'Let’s try that again.';
  $('error-message').textContent = error.message || String(error);
  $('retry-btn').hidden = !retry || busy();
  $('error-banner').hidden = false;
}
function clearError() { $('error-banner').hidden = true; }
$('dismiss-error').onclick = clearError;

function dialog(title, content, actions = [], kicker = 'EPILOGUE') {
  const modal = $('modal');
  $('modal-title').textContent = title; $('modal-kicker').textContent = kicker;
  $('modal-body').replaceChildren(...(Array.isArray(content) ? content : [el('p','',content)]));
  $('modal-actions').replaceChildren();
  for (const action of actions) {
    const button = el('button', action.primary ? 'primary' : 'secondary', action.label);
    button.onclick = action.run; $('modal-actions').append(button);
  }
  if (!modal.open) modal.showModal();
}
const closeDialog = () => $('modal').close();
$('modal-close').onclick = closeDialog;
$('modal').onclick = (event) => { if (event.target === $('modal')) { const r = $('modal').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDialog(); } };

async function setupFirebase() {
  if (!meta.auth_required) return;
  const [appSDK, sdk] = await Promise.all([
    import('https://www.gstatic.com/firebasejs/12.2.1/firebase-app.js'),
    import('https://www.gstatic.com/firebasejs/12.2.1/firebase-auth.js')
  ]);
  authSDK = sdk;
  firebaseAuth = sdk.getAuth(appSDK.getApps().length ? appSDK.getApp() : appSDK.initializeApp(meta.firebase));
  await sdk.setPersistence(firebaseAuth, sdk.inMemoryPersistence);
}

function signInDialog(after) {
  dialog('A space of your own.', [
    el('p','',`Sign in with Google to keep your case private and pick up where you left off. Your account includes ${money(meta.allowance_usd)} of live agent testing.`),
    el('p','', 'No payment details. No access code. All institutions in this demo are simulated.')
  ], [{label:'Not now',run:closeDialog},{label:'Continue with Google',primary:true,run:async () => {
    const button = $('modal-actions').lastElementChild;
    button.disabled = true; button.textContent = 'Connecting to Google…';
    try {
      if (!firebaseAuth) throw new Error('Sign-in is still loading. Check your connection and try again.');
      const credential = await authSDK.signInWithPopup(firebaseAuth, new authSDK.GoogleAuthProvider());
      await api('/api/session', {id_token:await credential.user.getIdToken()});
      await authSDK.signOut(firebaseAuth);
      await loadAccount(); closeDialog(); connectFeed();
      await refresh();
      if (after) await after();
    } catch (error) {
      const messages = {'auth/popup-closed-by-user':'Sign-in was closed. Try again whenever you’re ready.', 'auth/popup-blocked':'Your browser blocked the sign-in window. Allow pop-ups for this site, then try again.', 'auth/unauthorized-domain':'Sign-in is not configured for this address yet. Please use the main demo address.'};
      $('modal-body').querySelector('.modal-error')?.remove();
      const msg = el('p','modal-error', messages[error.code] || (error.code ? 'Google sign-in is unavailable right now. Please try again.' : error.message));
      msg.setAttribute('role','alert'); $('modal-body').append(msg);
    } finally { button.disabled = false; button.textContent = 'Continue with Google'; }
  }}], 'YOUR PRIVATE WORKSPACE');
}

async function loadAccount() {
  try { const account = await api('/api/account'); user = account.user; }
  catch (e) { if (e.status !== 401) throw e; user = null; }
  $('account-btn').textContent = user ? (user.name?.split(' ')[0] || 'Your account') : 'Sign in · $3 included';
  $('account-btn').disabled = false;
}
function openAccount() {
  if (!user) return signInDialog();
  dialog('Your workspace', [el('p','',user.email || user.name), el('p','',`${money(state?.budget?.remaining_usd ?? meta.allowance_usd)} of your test allowance remains. Starting a new case does not refill it.`)],
    [{label:'Close',run:closeDialog}, ...(meta.auth_required ? [{label:'Sign out',run:async () => { try { await api('/api/logout', {}); feed?.close(); feed = null; user = null; state = null; clearViews(); closeDialog(); await loadAccount(); } catch(e) { showError(e); } }}] : [])], 'ACCOUNT');
}
$('account-btn').onclick = openAccount;

const CATEGORY_LABELS = {financial:'Money & accounts',subscriptions:'Subscriptions & services',utilities:'The house',government:'Government',insurance:'Insurance',identity:'Identity protection',benefits:'Money owed to the family',memorial:'Memorial',digital_legacy:'Photos, memories & digital life'};
const STATUS_LABELS = {pending:'queued',in_progress:'working',waiting_response:'awaiting reply',needs_decision:'needs you',follow_up:'will chase',done:'settled',dismissed:'set aside'};

function clearViews() {
  $('intake-view').hidden = false; $('dashboard-view').hidden = true; $('intake-progress').hidden = true;
  $('activity-feed').replaceChildren(); $('intake-feed').replaceChildren(); seenActivity.clear();
  decisionSignature = ''; timelineSignature = ''; matterSignature = ''; seenError = null; clearError(); updateControls();
}
function updateControls() {
  const active = Boolean(busy());
  $('begin-btn').disabled = active;
  $('seed-btn').disabled = active;
  $('narrative').disabled = active; $('documents').disabled = active;
  $('reset-btn').disabled = active;
  const exhausted = state?.budget?.remaining_usd <= 0;
  document.querySelectorAll('.clock-btn, #continue-btn, .option-btn').forEach(b => b.disabled = active || exhausted || meta.preview && b.classList.contains('clock-btn'));
  $('pause-btn').hidden = !active || !state?.case;
  $('continue-btn').hidden = active || meta.preview;
  $('pause-btn').disabled = false;
  $('retry-btn').disabled = active;
  $('busy-dot').className = 'status-dot ' + (active ? 'working' : 'idle');
  $('work-label').textContent = active ? 'Working quietly' : state?.error ? 'Paused' : 'On watch';
}
function render() {
  if (!state) return;
  updateControls();
  if (state.error && state.error.id !== seenError) { seenError = state.error.id; showError(state.error, true); }
  const b = state.budget;
  if (b) {
    $('budget-remaining').textContent = money(b.remaining_usd) + ' left';
    $('budget-fill').style.width = Math.min(100, 100 * b.remaining_usd / b.limit_usd) + '%';
    $('budget-detail').textContent = `${money(b.spent_usd)} used of ${money(b.limit_usd)} · ${b.requests} model requests` + (b.reserved_usd ? ' · request in progress' : '');
  }
  const intake = !state.case || !state.intake_complete;
  $('intake-view').hidden = !intake; $('dashboard-view').hidden = intake;
  if (intake) {
    $('intake-progress').hidden = state.status === 'idle';
    $('stage-read').className = state.case ? '' : 'active';
    $('stage-plan').className = state.case && !state.intake_complete ? 'active' : '';
    $('stage-work').className = state.intake_complete ? 'active' : '';
    $('intake-status').textContent = state.intake_complete ? 'The plan is ready. Beginning the first day’s work…' : state.case ? 'Making a thoughtful plan for every matter…' : 'Reading what you shared…';
    if (state.activity) state.activity.slice().reverse().forEach(appendActivity);
    return;
  }
  const c = state.case, s = state.stats, first = c.survivor.full_name.split(' ')[0] || 'there';
  $('case-line').textContent = `The affairs of ${c.deceased.full_name}`;
  $('sim-date').textContent = new Date(s.sim_today + 'T00:00:00').toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'});
  const open = state.decisions.filter(d => d.status === 'open');
  $('hero-line').textContent = state.error ? `We’ve saved your place, ${first}. Continue whenever you’re ready.` : open.length ? `${open.length === 1 ? 'One thing needs' : open.length + ' things need'} your voice, ${first}.` : `${first}, a little less on your shoulders.`;
  const stats = [[`${s.settled} / ${s.total_matters}`,'matters settled'],[s.in_motion,'moving forward'],[s.hours_given_back + ' h','estimated time given back']];
  if (state.vault) stats.push([state.vault.certified_death_certificate,'certified copies in the vault']);
  const row = $('stats-row'); row.replaceChildren();
  for (const [value,label] of stats) { const box = el('div','stat'); box.append(el('div','stat-num',String(value)),el('div','stat-label',label)); row.append(box); }
  const percent = s.total_matters ? Math.round(100*s.settled/s.total_matters) : 0;
  $('progress-fill').style.width = percent+'%'; $('case-progress').setAttribute('aria-valuenow',percent);
  renderDecisions(open); renderMatters(); renderTimeline();
  for (const event of state.activity.slice().reverse()) appendActivity(event);
  $('note-section').hidden = !state.weekly_note;
  $('weekly-note').textContent = state.weekly_note || '';
}
function renderDecisions(open) {
  $('decisions-section').hidden = !open.length; $('decision-count').textContent = open.length;
  const signature = JSON.stringify(open);
  if (signature === decisionSignature) return;
  decisionSignature = signature;
  const wrap = $('decision-cards'); wrap.replaceChildren();
  for (const d of open) {
    const card = el('article','decision-card');
    card.append(el('span','urgency-chip urgency-'+d.urgency,d.urgency === 'whenever' ? 'Whenever you’re ready' : d.urgency.replace('_',' ')),el('h3','decision-q',d.question),el('p','decision-context',d.context));
    const options = el('div','decision-options');
    for (const o of d.options) {
      const button = el('button','option-btn'); button.append(el('span','opt-label',o.label),el('span','opt-consequence',o.consequence));
      if (d.recommendation === o.id) button.append(el('span','opt-rec','Epilogue’s suggestion'));
      button.disabled = Boolean(busy()); button.onclick = () => confirmDecision(d,o); options.append(button);
    }
    card.append(options); wrap.append(card);
  }
}
function confirmDecision(d,o) {
  const note = el('textarea'); note.id = 'decision-note'; note.rows = 3; note.maxLength = 2000; note.placeholder = 'Anything else you’d like Epilogue to know?';
  const label = el('label','field-label','Add a note (optional)'); label.htmlFor = note.id;
  dialog(o.label, [el('p','',o.consequence), ...(d.authorizes_amount_usd && o.authorizes ? [el('p','',`This choice authorizes up to ${money(d.authorizes_amount_usd)} in simulated money movements.`)] : []), label,note], [{label:'Go back',run:closeDialog},{label:'Confirm my choice',primary:true,run:async () => {
    const btn = $('modal-actions').lastElementChild; btn.disabled = true;
    try { await mutate(`/api/decisions/${d.id}/resolve`,{option_id:o.id,note:note.value}); closeDialog(); notify('Your choice is saved. Epilogue will take it from here.'); }
    catch(e) { closeDialog(); showError(e); } finally { btn.disabled = false; }
  }}], 'YOUR DECISION');
}
function renderMatters() {
  const wrap = $('matters'); const search = $('matter-search').value.trim().toLowerCase(); const filter = $('matter-filter').value;
  const signature = JSON.stringify([state.tasks,search,filter]);
  if (signature === matterSignature) return;
  matterSignature = signature;
  const tasks = state.tasks.filter(t => (t.title+' '+t.why+' '+(CATEGORY_LABELS[t.category]||t.category)).toLowerCase().includes(search) && (filter === 'all' || filter === 'active' && !['done','dismissed'].includes(t.status) || filter === t.status));
  wrap.replaceChildren();
  if (!tasks.length) { wrap.append(el('p','empty-state',state.tasks.length ? 'No matters match this view. Try another search or filter.' : 'Your plan is taking shape. Matters will appear here as they are discovered.')); return; }
  const groups = {}; for (const t of tasks) (groups[t.category] ||= []).push(t);
  for (const cat of [...Object.keys(CATEGORY_LABELS),...Object.keys(groups).filter(k=>!CATEGORY_LABELS[k])]) {
    if (!groups[cat]) continue;
    const group = el('div','matter-group'); group.append(el('h3','matter-group-title',CATEGORY_LABELS[cat] || cat));
    for (const task of groups[cat]) {
      const button = el('button','matter'); const title = el('span','matter-title',task.title);
      if (task.why) title.append(el('span','matter-why',task.why));
      button.append(title,el('span','chip '+task.status,STATUS_LABELS[task.status]||task.status));
      button.onclick = () => { const notes = el('ul','detail-list'); for (const n of task.notes || []) notes.append(el('li','',n)); dialog(task.title,[el('p','',task.why),el('p','',`Status: ${STATUS_LABELS[task.status] || task.status}`),notes], [{label:'Close',run:closeDialog}], CATEGORY_LABELS[task.category] || 'MATTER'); };
      group.append(button);
    }
    wrap.append(group);
  }
}
$('matter-search').oninput = renderMatters; $('matter-filter').onchange = renderMatters;
function renderTimeline() {
  const signature = JSON.stringify(state.timeline);
  if (timelineSignature === signature) return; timelineSignature = signature;
  $('timeline').replaceChildren();
  if (!state.timeline.length) $('timeline').append(el('p','empty-state','The first chapter is just beginning.'));
  for (const event of state.timeline.slice(0,60)) {
    const item = el('div','tl-item '+event.kind); item.append(el('div','tl-date',fmtDate(event.sim_date)+' · '+event.actor));
    const line = el('div','tl-summary',event.summary+' ');
    if (event.detail) { const peek = el('button','peek','Read record'); peek.onclick = () => dialog(event.summary,[el('p','',fmtDate(event.sim_date)+' · '+event.actor),el('div','letter',event.detail)],[{label:'Close',run:closeDialog}],'CASE CORRESPONDENCE'); line.append(peek); }
    item.append(line); $('timeline').append(item);
  }
}
function appendActivity(event) {
  const target = $('dashboard-view').hidden ? $('intake-feed') : $('activity-feed');
  const eventKey = target.id + ':' + event.id;
  if (!event.summary || event.kind === 'hello' || seenActivity.has(eventKey)) return;
  if (event.id) seenActivity.add(eventKey);
  const toolMessages = {get_matter:'Reviewing the next matter…', get_case_file:'Reviewing the case file…', get_playbook:'Checking the institution’s requirements…', list_matters:'Reviewing the plan…', consult_scribe:'Preparing a letter…', consult_advocate:'Looking for money owed to the family…', consult_sentinel:'Checking an identity protection signal…', submit_to_institution:'Checking and recording correspondence…', update_matter:'Saving progress…', ask_survivor:'Preparing a decision for you…', check_document_vault:'Checking the available documents…', search_benefit_records:'Looking for available benefits…', open_matter:'Adding a newly discovered matter…', current_date:'Checking the case clock…'};
  const summary = event.kind === 'tool_call' ? toolMessages[event.summary.replace(/^→\s*/, '')] || 'Reviewing the next step…' : event.summary;
  const line = el('div'); line.append(el('span','actor',event.actor ? event.actor+' · ' : ''),document.createTextNode(summary));
  target.append(line);
  while (target.childElementCount > 80) target.firstChild.remove(); target.scrollTop = target.scrollHeight;
}

function connectFeed() {
  if (feed || meta.auth_required && !user) return;
  feed = new EventSource('/api/feed');
  feed.onmessage = ({data}) => { try { const event = JSON.parse(data); appendActivity(event); if (event.kind !== 'hello') refreshSoon(); } catch {} };
  // Polling remains authoritative when proxies buffer or reconnect the live feed.
  feed.onerror = () => { refreshSoon(); };
}
async function refresh() {
  if (refreshing || meta.auth_required && !user) return;
  refreshing = true;
  try { state = await api('/api/state'); render(); }
  catch(e) { if (e.status === 401) { user = null; feed?.close(); feed = null; state = null; clearViews(); await loadAccount(); } else showError(e); }
  finally { refreshing = false; }
}
function refreshSoon() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 600); }
async function mutate(path, data = {}) {
  requestBusy = true; updateControls(); clearError();
  try { const result = await api(path,data); await refresh(); return result; }
  finally { requestBusy = false; updateControls(); }
}
async function begin() {
  if (busy()) return;
  const narrative = $('narrative').value.trim(), documents = $('documents').value.trim();
  if (narrative.length < 10) { $('narrative-error').hidden = false; $('narrative').setAttribute('aria-invalid','true'); $('narrative').focus(); return; }
  $('narrative-error').hidden = true; $('narrative').removeAttribute('aria-invalid');
  if (meta.auth_required && !user) return signInDialog(begin);
  if (meta.access_code_required && !accessCode) {
    const input = el('input'); input.id='access-code'; input.type='password'; input.autocomplete='off';
    const label = el('label','field-label','Access code'); label.htmlFor=input.id;
    dialog('Welcome to the private demo.',[el('p','','Enter the code the host shared with you.'),label,input],[{label:'Cancel',run:closeDialog},{label:'Continue',primary:true,run:()=>{accessCode=input.value.trim();closeDialog();if(accessCode)begin();}}]); return;
  }
  try { $('intake-feed').replaceChildren(); seenActivity.clear(); await mutate('/api/case',{narrative,documents}); $('intake-progress').hidden=false; $('intake-progress').scrollIntoView({behavior:'smooth',block:'nearest'}); }
  catch(e) { if(e.status === 401) accessCode=''; showError(e); }
}
$('intake-form').onsubmit = (event) => { event.preventDefault(); begin(); };
$('narrative').oninput = () => { $('narrative-error').hidden = true; $('narrative').removeAttribute('aria-invalid'); };
$('seed-btn').onclick = async () => { try { const seed = await api('/api/seed'); $('narrative').value=seed.narrative; $('documents').value=seed.documents; $('narrative-error').hidden=true; $('narrative').removeAttribute('aria-invalid'); notify('The Mitchell family case is ready. Choose “Let Epilogue begin” to run the agent.'); } catch(e) { showError(e); } };
for (const button of document.querySelectorAll('.clock-btn')) button.onclick = async () => { try { await mutate('/api/clock/advance',{days:Number(button.dataset.days)}); } catch(e) { showError(e); } };
$('continue-btn').onclick = $('retry-btn').onclick = async () => { try { await mutate('/api/retry'); } catch(e) { showError(e); } };
$('pause-btn').onclick = async () => { try { await api('/api/pause',{}); $('pause-btn').disabled=true; notify('Pausing after the current model request. Any completed work will be saved.'); } catch(e) { showError(e); } };
$('reset-btn').onclick = () => dialog('Make room for a new case?', 'This replaces the case in your workspace. Export it first if you want to keep a copy. Your remaining test allowance stays the same.',[{label:'Keep this case',run:closeDialog},{label:'Start a new case',primary:true,run:async()=>{try{await mutate('/api/reset');clearViews();closeDialog();$('narrative').value='';$('documents').value='';notify('Your workspace is ready for a new case.');}catch(e){closeDialog();showError(e);}}}]);
$('export-btn').onclick = async () => { try { const data = await api('/api/export'); const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})); const a=el('a');a.href=url;a.download='epilogue-case.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Your case file has been exported.'); } catch(e) { showError(e); } };
$('about-btn').onclick = () => dialog('A real agent. A gentle rehearsal.',[
  el('p','','Epilogue reads the story, inventories the documents, builds a plan, and works through it with a team of AI specialists. Every letter and decision leaves a record.'),
  el('p','','The Mitchell family and all institutions are fictional. No letters are sent to real institutions, no money is transferred, and no real accounts are changed. The case clock advances only when you ask.'),
  el('p','',`Your inputs are processed by OpenAI. Hosted case records and your ${money(meta.allowance_usd || 3)} allowance are saved privately in Firebase. The allowance tracks estimated API cost; it is not cash or a purchased credit balance.`)
],[{label:'Understood',primary:true,run:closeDialog}],'ABOUT THE DEMO');

async function boot() {
  try {
    meta = await api('/api/meta');
    $('allowance-note').textContent = meta.preview ? 'Saved preview · no live model calls' : `${money(meta.allowance_usd)} of agent testing included per account. No payment details.`;
    await Promise.all([setupFirebase(),loadAccount()]);
    $('account-btn').onclick = openAccount;
    clearError(); updateControls();
    await refresh(); connectFeed();
  } catch(e) { $('account-btn').textContent='Retry connection';$('account-btn').disabled=false;$('account-btn').onclick=boot;showError(e); }
}
boot();
setInterval(() => { if (!document.hidden || busy()) refresh(); },5000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
