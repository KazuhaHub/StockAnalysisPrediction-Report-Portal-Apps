import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  List,
  Popconfirm,
  Space,
  Spin,
  Typography,
} from "antd";
import { PortalTextField } from "@portal-app/sdk";
import {
  BridgeObjectError,
  useAppDraft,
  useAppNavigation,
  useAppObjects,
  useAppPage,
  useAppPresentation,
  type AppObjectSummary,
} from "@portal-app/sdk/root-v2";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import "./style.css";

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

function noteBody(content: Uint8Array): string {
  const value: unknown = JSON.parse(decoder.decode(content));
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    typeof (value as Record<string, unknown>).body !== "string"
  )
    throw new Error("invalid note");
  return (value as { body: string }).body;
}

function noteLabel(body: string, fallback: string): string {
  return (
    body
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find(Boolean) || fallback
  ).slice(0, 80);
}

export function Application() {
  const { presentation } = useAppPresentation();
  const navigation = useAppNavigation();
  const objects = useAppObjects();
  const copy = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[
    presentation.locale
  ];
  const editing = navigation.path === "/editor";
  const [notes, setNotes] = useState<AppObjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [selectedID, setSelectedID] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState("");
  const [saved, setSaved] = useState("");
  const createRequest = useRef(crypto.randomUUID());

  function failureMessage(error: unknown): string {
    if (error instanceof BridgeObjectError) {
      if (error.code === "conflict") return copy.conflict;
      if (error.code === "storage_full") return copy.storageFull;
      if (error.code === "unavailable" || error.code === "unsupported")
        return copy.unavailable;
      if (error.code === "uncertain") return copy.uncertain;
    }
    return copy.saveFailed;
  }

  useEffect(() => {
    if (!objects.ready) return;
    let active = true;
    setLoading(true);
    setFailure(null);
    objects
      .list("note", undefined, 50)
      .then((result) => {
        if (active) setNotes([...result.items]);
      })
      .catch((error: unknown) => {
        if (active) setFailure(failureMessage(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // Object methods are stable across ordinary presentation changes.
  }, [objects.ready, objects.list]);

  async function refreshNotes(): Promise<void> {
    const result = await objects.list("note", undefined, 50);
    setNotes([...result.items]);
  }

  function newNote() {
    createRequest.current = crypto.randomUUID();
    setSelectedID(null);
    setRevision(0);
    setDraft("");
    setSaved("");
    setFailure(null);
    navigation.navigate("/editor");
  }

  async function openNote(id: string, signal: AbortSignal) {
    setBusy(true);
    setFailure(null);
    try {
      const note = await objects.get(id, signal);
      if (signal.aborted) return;
      const body = noteBody(note.content);
      setSelectedID(note.id);
      setRevision(note.revision);
      setDraft(body);
      setSaved(body);
      navigation.navigate("/editor");
    } catch (error) {
      if (!signal.aborted) setFailure(failureMessage(error));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  async function saveNote(signal: AbortSignal) {
    setBusy(true);
    setFailure(null);
    try {
      const body = draft;
      const content = encoder.encode(JSON.stringify({ body }));
      const label = noteLabel(body, copy.untitled);
      let currentID = selectedID;
      let currentRevision = revision;
      if (!currentID) {
        const created = await objects.create(
          {
            requestId: createRequest.current,
            collection: "note",
            label,
            mediaType: "application/json",
            content,
          },
          signal,
        );
        currentID = created.id;
        currentRevision = created.revision;
        createRequest.current = crypto.randomUUID();
        setSelectedID(created.id);
        setRevision(created.revision);
      } else {
        const updated = await objects.update(
          currentID,
          {
            expectedRevision: currentRevision,
            label,
            mediaType: "application/json",
            content,
          },
          signal,
        );
        setRevision(updated.revision);
      }
      if (signal.aborted) return;
      setSaved(body);
      await refreshNotes();
      navigation.navigate("/");
    } catch (error) {
      if (!signal.aborted) setFailure(failureMessage(error));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  async function deleteNote(signal: AbortSignal) {
    if (!selectedID) return;
    setBusy(true);
    setFailure(null);
    try {
      await objects.delete(selectedID, revision, signal);
      if (signal.aborted) return;
      setSelectedID(null);
      setRevision(0);
      setDraft("");
      setSaved("");
      await refreshNotes();
      navigation.navigate("/");
    } catch (error) {
      if (!signal.aborted) setFailure(failureMessage(error));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  useAppDraft(draft !== saved);
  useAppPage({
    title: copy.title,
    description: copy.description,
    actions: editing
      ? [
          {
            id: "save",
            label: copy.save,
            variant: "primary",
            loading: busy,
            disabled: !objects.ready,
            onAction: saveNote,
          },
          {
            id: "home",
            label: copy.home,
            disabled: !navigation.ready || busy,
            onAction: () => {
              navigation.navigate("/");
            },
          },
        ]
      : [
          {
            id: "new",
            label: copy.newNote,
            variant: "primary",
            disabled: !objects.ready || !navigation.ready,
            onAction: newNote,
          },
        ],
  });

  if (!objects.available)
    return <Alert type="warning" showIcon title={copy.unavailable} />;
  if (!objects.ready || loading) return <Spin aria-label={copy.loading} />;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {failure && <Alert type="error" showIcon title={failure} />}
      {editing ? (
        <>
          <PortalTextField
            label={copy.draft}
            value={draft}
            onChange={setDraft}
            multiline
            help={copy.draftHelp}
          />
          {selectedID && (
            <Popconfirm
              title={copy.deleteConfirm}
              okText={copy.deleteYes}
              cancelText={copy.deleteNo}
              onConfirm={() => {
                void deleteNote(new AbortController().signal);
              }}
            >
              <Button danger loading={busy}>
                {copy.delete}
              </Button>
            </Popconfirm>
          )}
        </>
      ) : notes.length === 0 ? (
        <Empty description={copy.emptyList} />
      ) : (
        <List
          dataSource={notes}
          renderItem={(note) => (
            <List.Item
              actions={[
                <Button
                  key="open"
                  type="link"
                  onClick={() => {
                    void openNote(note.id, new AbortController().signal);
                  }}
                >
                  {copy.open}
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={note.label}
                description={
                  <Typography.Text type="secondary">
                    {new Intl.DateTimeFormat(presentation.locale, {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: presentation.timeZone,
                    }).format(new Date(note.updatedAt))}
                  </Typography.Text>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Space>
  );
}
