import { useState } from "react";
import { Alert, Form, Space, Typography } from "antd";
import { PortalTextField } from "@portal-app/sdk";
import {
  useAppDraft,
  useAppNavigation,
  useAppPage,
  useAppPresentation,
} from "@portal-app/sdk/root-v2";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import "./style.css";

export function Application() {
  const { presentation } = useAppPresentation();
  const navigation = useAppNavigation();
  const copy = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW }[
    presentation.locale
  ];
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const editing = navigation.path === "/editor";
  useAppDraft(text !== "");
  useAppPage({
    title: editing ? copy.editorTitle : copy.title,
    description: copy.description,
    actions: editing
      ? [
          {
            id: "preview",
            label: copy.preview,
            variant: "primary",
            onAction: () => {
              setPreview(text);
            },
          },
          {
            id: "home",
            label: copy.home,
            disabled: !navigation.ready,
            onAction: () => {
              navigation.navigate("/");
            },
          },
        ]
      : [
          {
            id: "editor",
            label: copy.openEditor,
            variant: "primary",
            disabled: !navigation.ready,
            onAction: () => {
              navigation.navigate("/editor");
            },
          },
        ],
  });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Alert type="info" showIcon title={copy.temporary} />
      {editing ? (
        <>
          <Form layout="vertical" component="div">
            <PortalTextField
              label={copy.draft}
              value={text}
              onChange={setText}
              multiline
              help={copy.draftHelp}
            />
          </Form>
          {preview !== null && (
            <div role="status" aria-label={copy.preview}>
              <Typography.Paragraph
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >
                {preview || copy.empty}
              </Typography.Paragraph>
            </div>
          )}
        </>
      ) : (
        <Typography.Paragraph>{copy.introduction}</Typography.Paragraph>
      )}
    </Space>
  );
}
