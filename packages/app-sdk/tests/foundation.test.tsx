import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { usePortalLocale, usePortalResource, PortalPage, PortalState, PortalClient, PortalErrorBoundary, PortalTextField, PortalAppProvider } from '../src/index';

beforeEach(() => vi.stubGlobal('matchMedia', vi.fn(() => ({
  matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {},
}))));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test('panel language is the default and an explicit override can return to following it', () => {
  const parent = {} as Window, client = new PortalClient('fixture', { current: window, parent });
  let language!: ReturnType<typeof usePortalLocale>;
  function Probe() { language = usePortalLocale(client); return <span>{language.locale}</span>; }
  render(<Probe />);
  try {
    act(() => window.dispatchEvent(new MessageEvent('message', { source: parent, data: { type: 'rp:init', locale: 'zh-CN' } })));
    expect(language.locale).toBe('zh-CN');
    expect(language.selection).toBe('panel');
    act(() => language.setSelection('en-US'));
    act(() => window.dispatchEvent(new MessageEvent('message', { source: parent, data: { type: 'rp:theme', locale: 'zh-TW' } })));
    expect(language.locale).toBe('en-US');
    act(() => language.setSelection('panel'));
    expect(language.locale).toBe('zh-TW');
    act(() => window.dispatchEvent(new MessageEvent('message', { source: {} as Window, data: { type: 'rp:theme', locale: 'en' } })));
    expect(language.locale).toBe('zh-TW');
  } finally { client.dispose(); }
});

test('obsolete reads cannot overwrite a newer resource or reintroduce data after denial', async () => {
  let oldResolve!: (value: string) => void;
  const oldLoad = () => new Promise<string>(resolve => { oldResolve = resolve; });
  const newLoad = vi.fn(async () => 'current');
  let resource!: ReturnType<typeof usePortalResource<string>>;
  function Probe({ load }: { load: () => Promise<string> }) {
    resource = usePortalResource(load, 'empty'); return <span>{resource.data}</span>;
  }
  const view = render(<Probe load={oldLoad} />);
  view.rerender(<Probe load={newLoad} />);
  await waitFor(() => expect(resource.data).toBe('current'));
  act(() => oldResolve('obsolete'));
  await act(async () => {});
  expect(resource.data).toBe('current');
  const denied = async () => { throw { key: 'accessDenied', status: 403 }; };
  view.rerender(<Probe load={denied} />);
  await waitFor(() => expect(resource.loading).toBe(false));
  expect(resource.data).toBe('empty');
  expect(resource.errorKey).toBe('accessDenied');
});

test('common page and state expose a labelled main region and recoverable failure', () => {
  const retry = vi.fn();
  render(<PortalPage title="Fixture app" description="Current service state">
    <PortalState kind="error" title="Unavailable" description="Try again later" retryLabel="Retry" onRetry={retry} />
  </PortalPage>);
  expect(screen.getByRole('main', { name: 'Fixture app' })).toBeTruthy();
  expect(screen.getByRole('alert')).toBeTruthy();
  screen.getByRole('button', { name: 'Retry' }).click();
  expect(retry).toHaveBeenCalledTimes(1);
});

test('render failures expose a bounded fallback without rendering exception contents', () => {
  const silence = vi.spyOn(console, 'error').mockImplementation(() => {});
  function Broken(): never { throw new Error('private backend diagnostic must not be shown'); }
  try {
    render(<PortalErrorBoundary locale="en-US"><Broken /></PortalErrorBoundary>);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.queryByText(/private backend diagnostic/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  } finally { silence.mockRestore(); }
});

test('shared repeated fields retain unique real labels and secrets have no reveal control', () => {
  const update = vi.fn();
  render(<><PortalTextField label="First target" value="one" onChange={update} />
    <PortalTextField label="Second target" value="two" onChange={update} />
    <PortalTextField label="Provider credential" value="private-value" onChange={update} secret /></>);
  const first = screen.getByLabelText('First target') as HTMLInputElement;
  const second = screen.getByLabelText('Second target') as HTMLInputElement;
  expect(first.id).not.toBe(second.id);
  fireEvent.change(first, { target: { value: 'changed' } });
  expect(update).toHaveBeenCalledWith('changed');
  const secret = screen.getByLabelText('Provider credential') as HTMLInputElement;
  expect(secret.type).toBe('password');
  expect(secret.autocomplete).toBe('new-password');
  expect(screen.queryByRole('button')).toBeNull();
});


test('the document stays transparent until a trusted host theme arrives and tracks later changes', () => {
  const parent = {} as Window, client = new PortalClient('fixture', { current: window, parent });
  document.body.style.background = '';
  document.documentElement.style.colorScheme = '';
  const view = render(<PortalAppProvider client={client} locale="en-US"><span>Fixture</span></PortalAppProvider>);
  try {
    expect(document.body.style.background).toBe('');
    expect(document.documentElement.style.colorScheme).toBe('');
    act(() => window.dispatchEvent(new MessageEvent('message', { source: {} as Window,
      data: { type: 'rp:init', theme: { dark: false, colorBgLayout: '#ffffff' } } })));
    expect(document.body.style.background).toBe('');
    act(() => window.dispatchEvent(new MessageEvent('message', { source: parent,
      data: { type: 'rp:init', theme: { dark: false, colorBgLayout: '#f5f5f5' } } })));
    expect(document.body.style.background).toBe('rgb(245, 245, 245)');
    act(() => window.dispatchEvent(new MessageEvent('message', { source: parent,
      data: { type: 'rp:init', theme: { dark: true, colorBgLayout: '#000000', colorText: '#eeeeee' } } })));
    expect(document.body.style.background).toBe('rgb(0, 0, 0)');
    expect(document.documentElement.style.colorScheme).toBe('dark');
    act(() => window.dispatchEvent(new MessageEvent('message', { source: parent,
      data: { type: 'rp:theme', theme: { dark: false, colorBgLayout: '#f5f5f5' } } })));
    expect(document.body.style.background).toBe('rgb(245, 245, 245)');
    expect(document.documentElement.style.colorScheme).toBe('light');
  } finally {
    view.unmount(); client.dispose();
    document.body.style.background = ''; document.documentElement.style.colorScheme = '';
  }
});
