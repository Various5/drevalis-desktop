import { useState, useEffect, useCallback } from 'react';
import {
  Brain,
  Plus,
  Trash2,
  TestTube2,
  CheckCircle2,
  XCircle,
  Edit3,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { llmConfigs } from '@/lib/api';
import type { LLMConfig } from '@/types';

export function LLMSection() {
  const { toast } = useToast();
  const [configs, setConfigs] = useState<LLMConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<LLMConfig | null>(null);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string; response?: string }>>({});

  // Form
  const [formName, setFormName] = useState('');
  const [formBaseUrl, setFormBaseUrl] = useState('');
  const [formModel, setFormModel] = useState('');
  const [formApiKey, setFormApiKey] = useState('');
  const [formMaxTokens, setFormMaxTokens] = useState('4096');
  const [formTemperature, setFormTemperature] = useState('0.7');

  const resetForm = () => {
    setFormName('');
    setFormBaseUrl('');
    setFormModel('');
    setFormApiKey('');
    setFormMaxTokens('4096');
    setFormTemperature('0.7');
    setEditingConfig(null);
  };

  const fetchConfigs = useCallback(async () => {
    try {
      const res = await llmConfigs.list();
      setConfigs(res);
    } catch (err) {
      toast.error('Failed to load LLM configurations', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void fetchConfigs();
  }, [fetchConfigs]);

  const openCreateDialog = () => {
    resetForm();
    setDialogOpen(true);
  };

  const openEditDialog = (c: LLMConfig) => {
    setEditingConfig(c);
    setFormName(c.name);
    setFormBaseUrl(c.base_url);
    setFormModel(c.model_name);
    setFormApiKey('');
    setFormMaxTokens(String(c.max_tokens));
    setFormTemperature(String(c.temperature));
    setDialogOpen(true);
  };

  const handleSave = async () => {
    setCreating(true);
    try {
      if (editingConfig) {
        const updateData: Record<string, unknown> = {};
        if (formName.trim() !== editingConfig.name) updateData.name = formName.trim();
        if (formBaseUrl.trim() !== editingConfig.base_url) updateData.base_url = formBaseUrl.trim();
        if (formModel.trim() !== editingConfig.model_name) updateData.model_name = formModel.trim();
        if (formApiKey.trim()) updateData.api_key = formApiKey.trim();
        if (Number(formMaxTokens) !== editingConfig.max_tokens) updateData.max_tokens = Number(formMaxTokens);
        if (Number(formTemperature) !== editingConfig.temperature) updateData.temperature = Number(formTemperature);
        if (Object.keys(updateData).length > 0) {
          await llmConfigs.update(editingConfig.id, updateData);
        }
      } else {
        await llmConfigs.create({
          name: formName.trim(),
          base_url: formBaseUrl.trim(),
          model_name: formModel.trim(),
          api_key: formApiKey.trim() || undefined,
          max_tokens: Number(formMaxTokens),
          temperature: Number(formTemperature),
        });
      }
      toast.success(editingConfig ? 'LLM config updated' : 'LLM config added');
      setDialogOpen(false);
      resetForm();
      void fetchConfigs();
    } catch (err) {
      toast.error(editingConfig ? 'Failed to update LLM config' : 'Failed to add LLM config', { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const result = await llmConfigs.test(id);
      setTestResults((prev) => ({
        ...prev,
        [id]: {
          success: result.success,
          message: result.message,
          response: result.response_text ?? undefined,
        },
      }));
    } catch (err) {
      toast.error('LLM test request failed', { description: String(err) });
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: false, message: 'Test request failed' },
      }));
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await llmConfigs.delete(id);
      toast.success('LLM config deleted');
      void fetchConfigs();
    } catch (err) {
      toast.error('Failed to delete LLM config', { description: String(err) });
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-txt-primary">
          LLM Configurations
        </h3>
        <Button variant="primary" size="sm" onClick={openCreateDialog}>
          <Plus size={14} />
          Add Config
        </Button>
      </div>

      {configs.length === 0 ? (
        <EmptyState
          icon={Brain}
          title="No LLM configurations yet"
          description="Add an endpoint above (LM Studio, Ollama, OpenAI, or Anthropic) to power scripts."
        />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {configs.map((c) => {
            const testResult = testResults[c.id];
            return (
              <Card key={c.id} padding="md" className="flex flex-col">
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-semibold text-txt-primary truncate">
                      {c.name}
                    </h4>
                    <div className="flex items-center gap-1.5 mt-1">
                      <Badge variant="accent" className="text-[10px]">{c.model_name}</Badge>
                      {c.has_api_key && (
                        <Badge variant="info" className="text-[10px]">API key</Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleDelete(c.id)}
                    className="shrink-0 text-txt-tertiary hover:text-error"
                  >
                    <Trash2 size={12} />
                  </Button>
                </div>

                {/* Details */}
                <p className="text-[11px] text-txt-secondary font-mono mt-2 truncate">
                  {c.base_url}
                </p>
                <p className="text-[10px] text-txt-tertiary mt-1">
                  Max tokens: {c.max_tokens} | Temp: {c.temperature}
                </p>

                {/* Inline test result */}
                {testResult && (
                  <div className={[
                    'mt-2 text-[11px] px-2 py-1.5 rounded',
                    testResult.success
                      ? 'bg-success-muted text-success'
                      : 'bg-error-muted text-error',
                  ].join(' ')}>
                    <span className="flex items-center gap-1">
                      {testResult.success ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
                      {testResult.message}
                    </span>
                    {testResult.response && (
                      <p className="mt-1 text-[10px] text-txt-secondary line-clamp-2">
                        {testResult.response}
                      </p>
                    )}
                  </div>
                )}

                {/* Actions */}
                <div className="mt-auto pt-3 flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={testing === c.id}
                    onClick={() => void handleTest(c.id)}
                  >
                    <TestTube2 size={12} />
                    Test
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openEditDialog(c)}
                  >
                    <Edit3 size={12} />
                    Edit
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); resetForm(); }}
        title={editingConfig ? 'Edit LLM Configuration' : 'Add LLM Configuration'}
      >
        <div className="space-y-4">
          <Input
            label="Name"
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder="e.g., GPT-4 Local"
          />
          <Input
            label="Base URL"
            value={formBaseUrl}
            onChange={(e) => setFormBaseUrl(e.target.value)}
            placeholder="http://localhost:11434/v1"
          />
          <Input
            label="Model Name"
            value={formModel}
            onChange={(e) => setFormModel(e.target.value)}
            placeholder="e.g., llama3, gpt-4"
          />
          <Input
            label={editingConfig ? 'API Key (leave blank to keep current)' : 'API Key (optional)'}
            type="password"
            value={formApiKey}
            onChange={(e) => setFormApiKey(e.target.value)}
            placeholder="Optional API key..."
          />
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Max Tokens"
              type="number"
              value={formMaxTokens}
              onChange={(e) => setFormMaxTokens(e.target.value)}
            />
            <Input
              label="Temperature"
              type="number"
              value={formTemperature}
              onChange={(e) => setFormTemperature(e.target.value)}
              hint="0.0 = deterministic, 1.0 = creative"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => { setDialogOpen(false); resetForm(); }}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={creating}
            disabled={
              !formName.trim() || !formBaseUrl.trim() || !formModel.trim()
            }
            onClick={() => void handleSave()}
          >
            {editingConfig ? 'Save Changes' : 'Add Config'}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
