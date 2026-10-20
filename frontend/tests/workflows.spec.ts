import { test, expect, type Page } from '@playwright/test';

const user = {user_id: 'u1', email: 'researcher@example.test', plan: 'free', role: 'owner'};
const settings = {hosted: false, use_api: false, api_provider: 'openai', api_model: 'test-model',
  inference_mode: 'off', effective_provider: '', effective_model: '', local_server_url: '', daily_budget_usd: 0,
  budget_editable: true, providers: [{name: 'openai', label: 'OpenAI'}, {name: 'gemini', label: 'Gemini'}], route_history: []};
const session = {session_id: 's1', topic: 'Real session from API', status: 'review_done', project_id: 'p1'};
const detail = {session, papers: [{title: 'Evidence from API'}], hypotheses: [], runs: [], report: null,
  artifacts: {}, code_files: [], cost_usd: 0, waiting_step: null, interrupted: null, gap_report: 'Gaps'};

async function server(page: Page, overrides: Record<string, unknown> = {}, authenticated = true) {
  const writes: {path: string; body: Record<string, unknown>}[] = [];
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET') {
      const body = request.postDataJSON() || {};
      writes.push({path, body});
      if (path === '/api/auth/login') authenticated = true;
      await route.fulfill({json: path === '/api/sessions' ? {session_id: 's1'} : {status: 'ok'}});
      return;
    }
    const responses: Record<string, unknown> = {
      '/api/auth/me': {accounts: true, user: authenticated ? user : null, password_policy: {min_length: 8, max_length: 128}},
      '/api/access/state': {locked: false, signed_in: true},
      '/api/dashboard': {sessions: {total: 1, running: 0, waiting: 0}, spend: {today_usd: 0}, waiting_for_you: []},
      '/api/sessions': {sessions: [session]},
      '/api/sessions/s1': detail,
      '/api/sessions/s1/stages': {running: false, waiting_step: null, stages: [{key: 'papers', label: 'Collect papers', ready: true, done: true, path: 'common', missing: []}]},
      '/api/settings': settings,
      '/api/projects': {projects: [{project_id: 'p1', name: 'API project', description: '', sessions: 1, papers: 1, spend_usd: 0}]},
      '/api/projects/p1/graph': {project: {project_id: 'p1', name: 'API project', description: ''}},
      '/api/projects/p1/papers': {papers: [{title: 'Evidence from API'}]},
      '/api/account/credentials': {credentials: []},
      '/api/account/overview': {account: user},
      '/api/account/usage': {estimated_cost_usd: 0, requests: []},
      '/api/account/billing': {subscription: {status: 'none'}, invoices: []},
      '/api/local-models': {host: 'http://localhost:11434', reachable: true, problem: '', installed: [{name: 'test-local'}],
        chosen: {model: 'test-local', embed_model: 'test-embed', num_ctx: 8192}},
      '/api/backups': {backups: []},
      ...overrides,
    };
    if (!(path in responses)) {await route.fulfill({status: 404, json: {detail: `Unexpected endpoint: ${path}`}}); return;}
    await route.fulfill({json: responses[path]});
  });
  await page.routeWebSocket('**/ws/**', ws => {ws.send(JSON.stringify({type: 'log', data: {message: 'Live event from runner'}}));});
  return writes;
}

test('protected route, login, session creation sends real form fields only', async ({page}) => {
  const writes = await server(page, {}, false);
  await page.goto('/app/sessions/new');
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel('Email', {exact: true}).fill(user.email);
  await page.getByLabel('Password', {exact: true}).fill('test-password');
  await page.getByRole('button', {name: 'Sign in', exact: true}).click();
  await expect(page).toHaveURL(/\/app\/sessions\/new$/);
  await page.getByLabel('topic', {exact: true}).fill('Research topic');
  await page.getByLabel('Start after creating', {exact: false}).uncheck();
  await page.getByRole('button', {name: 'Create session'}).click();
  await expect(page.getByRole('heading', {name: session.topic})).toBeVisible();
  expect(writes.find(w => w.path === '/api/sessions')?.body).toMatchObject({topic: 'Research topic', autostart: false});
});

test('question approval restores from API after reload and sends numeric selection', async ({page}) => {
  const writes = await server(page, {
    '/api/sessions/s1': {...detail, waiting_step: 'question_selection', artifacts: {
      question_candidates: {version: 1, status: 'awaiting_approval', content: {questions: [{index: 1, text: 'Does X change Y?', compliance: 'pass'}]}},
    }},
    '/api/sessions/s1/stages': {running: true, waiting_step: 'question_selection', stages: []},
  });
  await page.goto('/app/sessions/s1');
  await page.reload();
  await expect(page.getByText('Does X change Y?').first()).toBeVisible();
  await page.getByRole('button', {name: 'Select question 1'}).click();
  await expect.poll(() => writes.find(w => w.path.endsWith('/select-question'))?.body).toEqual({choice: 1, override: false});
  await page.getByRole('button', {name: 'Log', exact: true}).click();
  await expect(page.getByText('Live event from runner').first()).toBeVisible();
});

test('hypothesis and plan gates submit reviewed content', async ({page}) => {
  const writes = await server(page, {'/api/sessions/s1': {...detail, artifacts: {
    hypotheses: {version: 1, status: 'awaiting_approval', content: {hypotheses: [{id: 'H1', testable: true, statement: 'A hypothesis'}, {id: 'H2', testable: false}]}},
    plan: {version: 1, status: 'awaiting_approval', content: {text: 'Original plan', tests: []}},
  }}});
  await page.goto('/app/sessions/s1');
  await page.getByRole('checkbox', {name: 'H1', exact: true}).check();
  await expect(page.getByRole('checkbox', {name: /H2/})).toBeDisabled();
  await page.getByRole('button', {name: 'Approve selected hypotheses'}).click();
  await expect.poll(() => writes.find(w => w.path.endsWith('/select-hypotheses'))?.body).toEqual({ids: ['H1']});
  await page.getByLabel('Plan text').fill('Reviewed plan');
  await page.getByRole('button', {name: 'Approve plan'}).click();
  await expect.poll(() => writes.find(w => w.path.endsWith('/plan'))?.body).toEqual({text: 'Reviewed plan', approve: true});
});

test('all management routes render API data without leaving the frontend', async ({page}) => {
  await server(page);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  for (const [path, title] of [
    ['projects', 'Projects'], ['projects/p1', 'API project'], ['library', 'Paper library'], ['usage', 'Usage'],
    ['settings/account', 'Account'], ['settings/api', 'Models & API keys'], ['settings/local-runner', 'Local models'],
    ['settings/billing', 'Billing'], ['settings/privacy', 'Data & backups'],
  ]) {
    await page.goto(`/app/${path}`);
    await expect(page.getByRole('heading', {name: title, exact: true}).first()).toBeVisible();
    expect(new URL(page.url()).host).toBe('127.0.0.1:4175');
    await expect(page.getByText('alice@uni.ac.uk')).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});

test('API credential is submitted and cleared, never placed in browser storage', async ({page}) => {
  const writes = await server(page);
  await page.goto('/app/settings/api');
  await page.getByLabel('Secret key').fill('test-secret-not-real-12345');
  await page.getByRole('button', {name: 'Save credential', exact: true}).click();
  await expect(page.getByLabel('Secret key')).toHaveValue('');
  expect(writes.find(w => w.path === '/api/account/credentials')?.body.key).toBe('test-secret-not-real-12345');
  expect(await page.evaluate(() => JSON.stringify({...localStorage, ...sessionStorage}))).not.toContain('test-secret');
});

test('verification submits one-time token only on explicit action', async ({page}) => {
  const writes = await server(page, {}, false);
  await page.goto('/verify-email?token=one-time-test');
  expect(writes).toHaveLength(0);
  await page.getByRole('button', {name: 'Verify email', exact: true}).click();
  await expect.poll(() => writes.filter(w => w.path === '/api/auth/verify').length).toBe(1);
  expect(writes[0].body).toEqual({token: 'one-time-test'});
});

test('source approval and model changes send the explicit user decision', async ({page}) => {
  const writes = await server(page, {'/api/sessions/s1': {...detail, artifacts: {
    source_check: {status: 'awaiting_approval', content: {reason: 'Source unavailable'}},
  }}});
  await page.goto('/app/sessions/s1');
  await page.getByRole('button', {name: 'Do not continue', exact: true}).click();
  await expect.poll(() => writes.find(w => w.path.endsWith('/source-decision'))?.body).toEqual({proceed: false});
  await page.goto('/app/settings/api');
  await page.getByLabel('Enable model API').check();
  await page.getByLabel('Model', {exact: true}).fill('chosen-model');
  await page.getByRole('button', {name: 'Save model settings'}).click();
  await expect.poll(() => writes.find(w => w.path === '/api/settings')?.body).toMatchObject({use_api: true, api_model: 'chosen-model'});
});

test('report download respects backend format fallback and filename', async ({page}) => {
  await server(page);
  await page.route('**/api/sessions/s1/report/pdf', route => route.fulfill({
    contentType: 'text/html', headers: {'Content-Disposition': 'attachment; filename="report.html"'},
    body: '<h1>Report fallback</h1>',
  }));
  await page.goto('/app/sessions/s1');
  await page.getByRole('button', {name: 'Report', exact: true}).click();
  const file = page.waitForEvent('download');
  await page.getByRole('button', {name: 'pdf', exact: true}).click();
  expect((await file).suggestedFilename()).toBe('report.html');
});
