"use client";

import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Upload, FileText, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface DocumentUploaderProps {
  onFileSelect: (file: File | null, text: string) => void;
  maxSize?: number;
  acceptedTypes?: string[];
}

export const DocumentUploader = ({
  onFileSelect,
  maxSize = 10 * 1024 * 1024, // 10MB
  acceptedTypes = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"],
}: DocumentUploaderProps) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [textInput, setTextInput] = useState("");
  const [useTextInput, setUseTextInput] = useState(true);

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (file) {
        setSelectedFile(file);
        setUseTextInput(false);
        onFileSelect(file, "");
      }
    },
    [onFileSelect]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    maxSize,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/plain": [".txt"],
    },
    multiple: false,
  });

  const handleTextChange = (value: string) => {
    setTextInput(value);
    if (value.trim()) {
      setUseTextInput(true);
      onFileSelect(null, value);
    }
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setUseTextInput(true);
    onFileSelect(null, textInput);
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <Button
          type="button"
          variant={useTextInput ? "default" : "outline"}
          onClick={() => setUseTextInput(true)}
        >
          Вставить текст
        </Button>
        <Button
          type="button"
          variant={!useTextInput ? "default" : "outline"}
          onClick={() => setUseTextInput(false)}
        >
          Загрузить файл
        </Button>
      </div>

      {useTextInput ? (
        <div className="space-y-2">
          <Label htmlFor="text-input">Текст документа</Label>
          <Textarea
            id="text-input"
            value={textInput}
            onChange={(e) => handleTextChange(e.target.value)}
            placeholder="Вставьте текст судебного документа здесь..."
            className="min-h-[300px]"
          />
          {textInput && (
            <p className="text-sm text-muted-foreground">
              Символов: {textInput.length} | Слов: {textInput.split(/\s+/).filter(Boolean).length}
            </p>
          )}
        </div>
      ) : (
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            isDragActive
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-primary/50"
          }`}
        >
          <input {...getInputProps()} />
          <Upload className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
          {isDragActive ? (
            <p className="text-lg">Отпустите файл здесь...</p>
          ) : (
            <>
              <p className="text-lg mb-2">
                Перетащите файл сюда или нажмите для выбора
              </p>
              <p className="text-sm text-muted-foreground">
                Поддерживаются: PDF, DOCX, TXT (макс. {maxSize / 1024 / 1024}MB)
              </p>
            </>
          )}
        </div>
      )}

      {selectedFile && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary" />
                <div>
                  <p className="font-medium">{selectedFile.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {(selectedFile.size / 1024).toFixed(2)} KB
                  </p>
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={handleRemoveFile}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

