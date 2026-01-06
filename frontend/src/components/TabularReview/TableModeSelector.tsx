"use client"

import React from "react"
import { Box, FormControl, InputLabel, Select, MenuItem, Typography, Stack } from "@mui/material"

interface TableModeSelectorProps {
  mode: "document" | "entity" | "fact"
  onChange: (mode: "document" | "entity" | "fact") => void
}

export const TableModeSelector: React.FC<TableModeSelectorProps> = ({ mode, onChange }) => {
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          Режим таблицы:
        </Typography>
        <FormControl size="small">
          <InputLabel id="table-mode-label">Режим</InputLabel>
          <Select
            labelId="table-mode-label"
            value={mode}
            label="Режим"
            onChange={(e) => onChange(e.target.value as "document" | "entity" | "fact")}
          >
            <MenuItem value="document">Document Table</MenuItem>
            <MenuItem value="entity">Entity Table</MenuItem>
            <MenuItem value="fact">Fact Table</MenuItem>
          </Select>
        </FormControl>
      </Stack>
    </Box>
  )
}


