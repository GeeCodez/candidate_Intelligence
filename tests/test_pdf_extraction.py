import os
import sys
import tempfile
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_extraction import PDFExtractor, PDFExtractionError, extract_cv_content
import pymupdf


class MockUploadedFile:
    def __init__(self, filename, content):
        self.name = filename
        self.content = content
        self.file = BytesIO(content)
    
    def read(self):
        return self.file.read()


def test_pdf_validation():
    extractor = PDFExtractor()
    
    try:
        extractor.validate_pdf(None)
        assert False
    except PDFExtractionError as e:
        assert "No PDF file provided" in str(e)
    
    txt_file = MockUploadedFile("test.txt", b"test content")
    try:
        extractor.validate_pdf(txt_file)
        assert False
    except PDFExtractionError as e:
        assert "Unsupported file type" in str(e)
    
    pdf_file = MockUploadedFile("test.pdf", b"test content")
    result = extractor.validate_pdf(pdf_file)
    assert result == True
    
    print("[PASS] PDF validation tests passed")


def test_pdf_extraction_with_sample():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "John Doe\nBackend Developer\n\nSkills:\nPython, Django, PostgreSQL\n\nGitHub:\nhttps://github.com/johndoe")
    
    pdf_bytes = doc.tobytes()
    doc.close()
    
    uploaded_file = MockUploadedFile("test.pdf", pdf_bytes)
    result = extract_cv_content(uploaded_file)
    
    assert 'text' in result
    assert 'urls' in result
    assert 'page_count' in result
    assert "John Doe" in result['text']
    assert "Backend Developer" in result['text']
    assert "Python" in result['text']
    assert "https://github.com/johndoe" in result['text']
    assert result['page_count'] == 1
    
    print("[PASS] PDF extraction tests passed")
    print(f"  - Extracted {len(result['text'])} characters of text")
    print(f"  - Found {len(result['urls'])} URLs")
    print(f"  - Text preview: {result['text'][:100]}...")


def test_empty_pdf():
    doc = pymupdf.open()
    doc.new_page()
    
    pdf_bytes = doc.tobytes()
    doc.close()
    
    uploaded_file = MockUploadedFile("empty.pdf", pdf_bytes)
    result = extract_cv_content(uploaded_file)
    
    assert result['text'] == ''
    assert result['urls'] == []
    assert result['page_count'] == 1
    
    print("[PASS] Empty PDF test passed")


def test_multiple_pages():
    doc = pymupdf.open()
    
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Page 1 Content\nhttps://example.com/page1")
    
    page2 = doc.new_page()
    page2.insert_text((50, 50), "Page 2 Content\nhttps://example.com/page2")
    
    pdf_bytes = doc.tobytes()
    doc.close()
    
    uploaded_file = MockUploadedFile("multipage.pdf", pdf_bytes)
    result = extract_cv_content(uploaded_file)
    
    assert result['page_count'] == 2
    assert "Page 1 Content" in result['text']
    assert "Page 2 Content" in result['text']
    assert "https://example.com/page1" in result['urls']
    assert "https://example.com/page2" in result['urls']
    
    print("[PASS] Multi-page PDF test passed")


def test_empty_upload():
    uploaded_file = MockUploadedFile("empty.pdf", b"")
    
    try:
        extract_cv_content(uploaded_file)
        assert False
    except PDFExtractionError as e:
        assert "empty" in str(e).lower()
    
    print("[PASS] Empty upload test passed")


if __name__ == "__main__":
    print("Running PDF extraction tests...\n")
    
    try:
        test_pdf_validation()
        test_pdf_extraction_with_sample()
        test_empty_pdf()
        test_multiple_pages()
        test_empty_upload()
        
        print("\n[PASS] All tests passed successfully!")
        
    except Exception as e:
        print(f"\n[FAIL] Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)