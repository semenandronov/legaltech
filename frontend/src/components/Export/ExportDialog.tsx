import React, { useState } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  FormGroup,
  FormControlLabel,
  Checkbox,
  RadioGroup,
  Radio,
  Typography,
  Box,
  Stack,
  CircularProgress,
  Alert,
} from '@mui/material'
import {
  FileDownload as DownloadIcon,
  Email as EmailIcon,
  CloudUpload as CloudIcon,
} from '@mui/icons-material'

export type ExportFormat = 'REL' | 'PDF' | 'CSV' | 'JSON' | 'EDRM_XML'

export interface ExportOptions {
  formats: ExportFormat[]
  includeAuditLog: boolean
  includeCertification: boolean
  includeChainOfCustody: boolean
  filters?: {
    status?: string[]
    dateFrom?: string
    dateTo?: string
    searchQuery?: string
  }
  destination?: 'download' | 'email' | 's3'
}

interface ExportDialogProps {
  caseId?: string
  onClose: () => void
  onExport: (options: ExportOptions) => Promise<void>
  open: boolean
}

const ExportDialog: React.FC<ExportDialogProps> = ({
  onClose,
  onExport,
  open,
}) => {
  const [formats, setFormats] = useState<ExportFormat[]>(['REL'])
  const [includeAuditLog, setIncludeAuditLog] = useState(true)
  const [includeCertification, setIncludeCertification] = useState(false)
  const [includeChainOfCustody, setIncludeChainOfCustody] = useState(false)
  const [destination, setDestination] = useState<'download' | 'email' | 's3'>('download')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleFormatToggle = (format: ExportFormat) => {
    setFormats(prev => {
      if (prev.includes(format)) {
        return prev.filter(f => f !== format)
      }
      return [...prev, format]
    })
  }

  const handleExport = async () => {
    if (formats.length === 0) {
      setError('Выберите хотя бы один формат')
      return
    }

    setError(null)
    setLoading(true)
    try {
      await onExport({
        formats,
        includeAuditLog,
        includeCertification,
        includeChainOfCustody,
        destination
      })
      onClose()
    } catch (err) {
      console.error('Export error:', err)
      setError('Ошибка при экспорте')
    } finally {
      setLoading(false)
    }
  }

  const formatLabels: Record<ExportFormat, string> = {
    REL: 'REL format (для суда)',
    PDF: 'PDF report (with bates numbers)',
    CSV: 'CSV (with metadata)',
    JSON: 'JSON (для API integration)',
    EDRM_XML: 'EDRM XML',
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Typography variant="h6">Export Documents</Typography>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={3}>
          {error && (
            <Alert severity="error" onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          {/* Formats */}
          <Box>
            <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
              Formats
            </Typography>
            <FormGroup>
              {(Object.keys(formatLabels) as ExportFormat[]).map((format) => (
                <FormControlLabel
                  key={format}
                  control={
                    <Checkbox
                      checked={formats.includes(format)}
                      onChange={() => handleFormatToggle(format)}
                      size="small"
                    />
                  }
                  label={formatLabels[format]}
                />
              ))}
            </FormGroup>
          </Box>

          {/* Options */}
          <Box>
            <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
              Options
            </Typography>
            <FormGroup>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={includeAuditLog}
                    onChange={(e) => setIncludeAuditLog(e.target.checked)}
                    size="small"
                    required
                  />
                }
                label={
                  <Typography>
                    Include audit log <Typography component="span" color="error.main">(REQUIRED!)</Typography>
                  </Typography>
                }
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={includeCertification}
                    onChange={(e) => setIncludeCertification(e.target.checked)}
                    size="small"
                  />
                }
                label="Certification statement"
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={includeChainOfCustody}
                    onChange={(e) => setIncludeChainOfCustody(e.target.checked)}
                    size="small"
                  />
                }
                label="Chain of custody"
              />
            </FormGroup>
          </Box>

          {/* Destination */}
          <Box>
            <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
              Destination
            </Typography>
            <RadioGroup
              value={destination}
              onChange={(e) => setDestination(e.target.value as 'download' | 'email' | 's3')}
            >
              <FormControlLabel
                value="download"
                control={<Radio size="small" />}
                label={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <DownloadIcon fontSize="small" />
                    <Typography>Download</Typography>
                  </Stack>
                }
              />
              <FormControlLabel
                value="email"
                control={<Radio size="small" />}
                label={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <EmailIcon fontSize="small" />
                    <Typography>Email</Typography>
                  </Stack>
                }
              />
              <FormControlLabel
                value="s3"
                control={<Radio size="small" />}
                label={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <CloudIcon fontSize="small" />
                    <Typography>S3</Typography>
                  </Stack>
                }
              />
            </RadioGroup>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button
          onClick={onClose}
          disabled={loading}
          variant="outlined"
        >
          Cancel
        </Button>
        <Button
          onClick={handleExport}
          disabled={loading || formats.length === 0}
          variant="contained"
          startIcon={loading ? <CircularProgress size={16} /> : <DownloadIcon />}
        >
          {loading ? 'Exporting...' : 'Export'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default ExportDialog
