"use client"

import React, { useState } from "react"
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Stack,
  Typography,
  Paper,
  Chip,
  Radio,
  RadioGroup,
  FormControlLabel,
  FormControl,
  FormLabel,
  Box,
  Divider,
} from "@mui/material"
import {
  Check as CheckIcon,
  Warning as WarningIcon,
} from "@mui/icons-material"
import { Candidate } from "@/services/tabularReviewApi"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { toast } from "sonner"

interface ConflictResolutionModalProps {
  open: boolean
  onClose: () => void
  reviewId: string
  fileId: string
  columnId: string
  columnLabel: string
  candidates: Candidate[]
  onResolved: () => void
}

export const ConflictResolutionModal: React.FC<ConflictResolutionModalProps> = ({
  open,
  onClose,
  reviewId,
  fileId,
  columnId,
  columnLabel,
  candidates,
  onResolved,
}) => {
  const [selectedCandidateId, setSelectedCandidateId] = useState<number>(0)
  const [resolutionMethod, setResolutionMethod] = useState<'select' | 'merge' | 'n_a'>('select')
  const [resolving, setResolving] = useState(false)

  const handleResolve = async () => {
    if (resolutionMethod === 'n_a') {
      // For N/A, we don't need to select a candidate
      setResolving(true)
      try {
        await tabularReviewApi.resolveConflict(
          reviewId,
          fileId,
          columnId,
          0, // Not used for N/A
          'n_a'
        )
        toast.success("Conflict resolved: marked as N/A")
        onResolved()
        onClose()
      } catch (error: any) {
        toast.error("Failed to resolve conflict: " + (error.message || "Unknown error"))
      } finally {
        setResolving(false)
      }
    } else {
      setResolving(true)
      try {
        await tabularReviewApi.resolveConflict(
          reviewId,
          fileId,
          columnId,
          selectedCandidateId,
          resolutionMethod
        )
        toast.success("Conflict resolved successfully")
        onResolved()
        onClose()
      } catch (error: any) {
        toast.error("Failed to resolve conflict: " + (error.message || "Unknown error"))
      } finally {
        setResolving(false)
      }
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 2,
        },
      }}
    >
      <DialogTitle>
        <Stack direction="row" spacing={1} alignItems="center">
          <WarningIcon color="warning" />
          <Typography variant="h6">Resolve Conflict</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Column: {columnLabel}
        </Typography>
      </DialogTitle>

      <DialogContent>
        <Stack spacing={3}>
          <Paper
            elevation={0}
            sx={{
              bgcolor: "warning.light",
              p: 2,
              borderRadius: 1,
            }}
          >
            <Typography variant="body2" color="text.secondary">
              Multiple different values were found for this cell. Please select the correct value or mark as N/A.
            </Typography>
          </Paper>

          <FormControl component="fieldset">
            <FormLabel component="legend">Resolution Method</FormLabel>
            <RadioGroup
              value={resolutionMethod}
              onChange={(e) => setResolutionMethod(e.target.value as 'select' | 'merge' | 'n_a')}
            >
              <FormControlLabel
                value="select"
                control={<Radio />}
                label="Select one candidate value"
              />
              <FormControlLabel
                value="merge"
                control={<Radio />}
                label="Merge values (combine information)"
              />
              <FormControlLabel
                value="n_a"
                control={<Radio />}
                label="Mark as N/A (not applicable)"
              />
            </RadioGroup>
          </FormControl>

          {resolutionMethod !== 'n_a' && (
            <>
              <Divider />
              <Typography variant="subtitle2" fontWeight={600}>
                Select Candidate ({candidates.length} found)
              </Typography>

              <Stack spacing={2}>
                {candidates.map((candidate, idx) => (
                  <Paper
                    key={idx}
                    elevation={0}
                    sx={{
                      p: 2,
                      borderRadius: 1,
                      border: 2,
                      borderColor: selectedCandidateId === idx ? "primary.main" : "divider",
                      bgcolor: selectedCandidateId === idx ? "primary.light" : "background.paper",
                      cursor: "pointer",
                      "&:hover": {
                        bgcolor: "action.hover",
                      },
                    }}
                    onClick={() => setSelectedCandidateId(idx)}
                  >
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                      <Radio
                        checked={selectedCandidateId === idx}
                        onChange={() => setSelectedCandidateId(idx)}
                        onClick={(e) => e.stopPropagation()}
                      />
                      <Chip
                        label={`Candidate ${idx + 1}`}
                        size="small"
                        color={selectedCandidateId === idx ? "primary" : "default"}
                      />
                      <Chip
                        label={`${Math.round(candidate.confidence * 100)}% confidence`}
                        size="small"
                        color={
                          candidate.confidence >= 0.9
                            ? "success"
                            : candidate.confidence >= 0.7
                            ? "warning"
                            : "error"
                        }
                      />
                      {idx === 0 && (
                        <Chip
                          label="Current"
                          size="small"
                          color="info"
                        />
                      )}
                    </Stack>

                    <Typography variant="body1" fontWeight={selectedCandidateId === idx ? 600 : 400}>
                      {candidate.value}
                    </Typography>

                    {candidate.normalized_value && candidate.normalized_value !== candidate.value && (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
                        Normalized: {candidate.normalized_value}
                      </Typography>
                    )}

                    {candidate.verbatim && (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary" fontWeight={600}>
                          Quote:
                        </Typography>
                        <Paper
                          elevation={0}
                          sx={{
                            bgcolor: "action.hover",
                            p: 1,
                            borderRadius: 0.5,
                            mt: 0.5,
                          }}
                        >
                          <Typography variant="body2" color="text.secondary" sx={{ fontStyle: "italic" }}>
                            "{candidate.verbatim}"
                          </Typography>
                        </Paper>
                      </Box>
                    )}

                    {candidate.reasoning && (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary" fontWeight={600}>
                          Reasoning:
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                          {candidate.reasoning}
                        </Typography>
                      </Box>
                    )}

                    <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                      {candidate.source_page && (
                        <Chip
                          label={`Page ${candidate.source_page}`}
                          size="small"
                          variant="outlined"
                        />
                      )}
                      {candidate.source_section && (
                        <Chip
                          label={candidate.source_section}
                          size="small"
                          variant="outlined"
                        />
                      )}
                      {candidate.extraction_method && (
                        <Chip
                          label={candidate.extraction_method}
                          size="small"
                          variant="outlined"
                        />
                      )}
                    </Stack>
                  </Paper>
                ))}
              </Stack>
            </>
          )}
        </Stack>
      </DialogContent>

      <DialogActions sx={{ p: 2, borderTop: 1, borderColor: "divider" }}>
        <Button onClick={onClose} disabled={resolving}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleResolve}
          disabled={resolving || (resolutionMethod !== 'n_a' && selectedCandidateId < 0)}
          startIcon={resolving ? undefined : <CheckIcon />}
        >
          {resolving ? "Resolving..." : "Resolve Conflict"}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

