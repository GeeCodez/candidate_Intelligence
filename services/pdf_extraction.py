import os
import re

import pymupdf


class PDFExtractionError(Exception):
    pass


class PDFExtractor:
    SUPPORTED_EXTENSIONS = {".pdf"}

    def validate_pdf(self, uploaded_file):
        if not uploaded_file:
            raise PDFExtractionError("No PDF file provided.")

        filename = uploaded_file.name
        extension = os.path.splitext(filename)[1].lower()

        if extension not in self.SUPPORTED_EXTENSIONS:
            raise PDFExtractionError(
                f"Unsupported file type: {extension}"
            )

        return True

    def extract_urls_from_page(self, page):
        urls = []

        # URLs embedded as clickable links
        for link in page.get_links():
            uri = link.get("uri")

            if uri:
                urls.append(uri)

        # URLs visible in the page text
        text = page.get_text()

        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        text_urls = re.findall(url_pattern, text)

        urls.extend(text_urls)

        return urls

    def extract_text_from_page(self, page):
        return page.get_text()

    def extract_from_pdf(self, uploaded_file):
        try:
            self.validate_pdf(uploaded_file)

            # Read the uploaded file directly into memory.
            pdf_bytes = uploaded_file.read()

            if not pdf_bytes:
                raise PDFExtractionError("The uploaded PDF is empty.")

            # Open PDF from memory. No permanent file storage required.
            doc = pymupdf.open(
                stream=pdf_bytes,
                filetype="pdf"
            )

            all_text = []
            all_urls = []

            for page in doc:
                page_text = self.extract_text_from_page(page)
                all_text.append(page_text)

                page_urls = self.extract_urls_from_page(page)
                all_urls.extend(page_urls)

            page_count = len(doc)

            doc.close()

            return {
                "text": "\n\n".join(all_text).strip(),
                "urls": list(dict.fromkeys(all_urls)),
                "page_count": page_count,
            }

        except PDFExtractionError:
            raise

        except Exception as e:
            raise PDFExtractionError(
                f"Failed to extract content from PDF: {str(e)}"
            )


def extract_cv_content(uploaded_file):
    extractor = PDFExtractor()
    return extractor.extract_from_pdf(uploaded_file)