import logging
import re
import json
from difflib import SequenceMatcher
from datetime import datetime
from io import StringIO
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTChar

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define alternative section names
alternative_names = {
    "protocol summary": ["clinical trial summary", "protocol summary", "synopsis"],
    "introduction": ["background"],
    "trial objectives, endpoints and estimads": ["OBJECTIVES", "TRIAL OBJECTIVES and ENDPOINTS", "STUDY OBJECTIVES", "HYPOTHESES, OBJECTIVES, AND ENDPOINTS"],
    "trial design": ["Trial Design", "Overall Study Design", "Overall Study Design and Plan", "Study Design", "STUDY"],
    "trial population": ["Study Population", "Patient Selection", "Selection of Study Population", "Subject Population", "Selection and Discontinuation of Subjects"],
    "trial intervention and concomitant therapy": ["Study Intervention", "Treatment", "INTERVENTION", "study treatment", "study treatments", "trial treatments"],
    "discontinuation of trial intervention and participant withdrawal from trial": ["discontinuation", "withdrawal"],
    "trial assessments and procedures": ["assessments", "procedures"],
    "statistical considerations": ["Statistical Analysis Plan"],
    "general considerations: regulatory, ethical, and trial oversight": ["ethic"],
    "general considerations: risk management and quality assurance": ["general", "consideration", "data"],
    "appendix: adverse events and serious adverse events – definitions, severity, and causality": ["adverse events", "appendix"]
}

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def match_sections(content, pdf_path):
    logger.info("Starting section matching process")
    matched_sections = {}
    last_matched_page = -1
    
    # Identify TOC pages using pdfminer
    toc_pages = identify_toc_pages_pdfminer(pdf_path)
    
    # Define the order of sections to search for
    section_order = list(alternative_names.keys())
    
    for main_section in section_order:
        logger.debug(f"Matching main section: '{main_section}'")
        main_section_content = None
        section_found = False
        
        for page_num in range(last_matched_page + 1, len(content)):
            if page_num + 1 in toc_pages:  # Add 1 because pdfminer uses 1-based page numbers
                continue  # Skip TOC pages
            
            main_section_content, end_reason = extract_section_from_items(content, page_num, main_section, alternative_names)
            
            if main_section_content:
                matched_sections[main_section] = main_section_content
                start_page = main_section_content['start_page']
                end_page = main_section_content['end_page']
                last_matched_page = end_page
                logger.info(f"Matched main section '{main_section}' from page {start_page} to {end_page}. Reason: {end_reason}")
                section_found = True
                break
        
        if not section_found:
            matched_sections[main_section] = create_empty_section()
            logger.warning(f"No match found for main section '{main_section}'")
            # Move to the next page for the next section search
            last_matched_page += 1
    
    return matched_sections

def create_empty_section():
    return {
        "content": "Not available",
        "start_page": None,
        "end_page": None,
        "section_num": None,
        "images": [],
        "tables": []
    }

def extract_section_from_items(content, start_page, target, alternative_names):
    logger.debug(f"Extracting section content for '{target}' starting from page {start_page}")
    section_content = []
    images = []
    tables = []
    started = False
    current_page = start_page
    section_num = None
    current_subsection = None
    end_reason = "Reached end of document"
    start_page_num = None

    def is_matching_heading(heading, target, alternative_names):
        cleaned_heading = re.sub(r'^\d+(\.\d+)*\s*', '', heading).strip().lower()
        
        # First, check for exact match with target
        if cleaned_heading == target.lower():
            logger.debug(f"Exact match found for '{target}': '{heading}'")
            return target

        # If no exact match with target, check for similarity with target
        if similarity(cleaned_heading, target.lower()) > 0.8:
            logger.debug(f"Similarity match found for '{target}': '{heading}'")
            return target

        # If still no match, check alternative names
        for alt_name in alternative_names.get(target, []):
            if cleaned_heading == alt_name.lower():
                logger.debug(f"Exact match found for alternative name '{alt_name}': '{heading}'")
                return alt_name
            if similarity(cleaned_heading, alt_name.lower()) > 0.8:
                logger.debug(f"Similarity match found for alternative name '{alt_name}': '{heading}'")
                return alt_name
        
        return None

    for page_num, page in enumerate(content[start_page:], start=start_page):
        current_page = page['page']
        
        for item in page['items']:
            item_type = item.get('type', '').lower()
            item_value = item.get('value', '')

            if item_type == 'heading':
                matched_name = is_matching_heading(item_value, target, alternative_names)
                if matched_name and not started:
                    started = True
                    start_page_num = current_page
                    section_num = extract_section_number(item_value)
                    section_content.append(item_value)
                    current_subsection = item_value
                    logger.info(f"Started section '{matched_name}' with number {section_num} on page {current_page}")
                elif started and is_next_main_section(item_value, section_num, target, alternative_names):
                    end_reason = f"Next main section found: '{item_value}'"
                    logger.info(f"Ended section '{target}' on page {current_page - 1}. {end_reason}")
                    return create_section_dict(section_content, current_page - 1, start_page_num, section_num, images, tables), end_reason
                elif started:
                    section_content.append(item_value)
                    current_subsection = item_value
            
            elif started:
                if item_type == 'text':
                    if current_subsection:
                        section_content.append(f"{current_subsection}:\n{item_value}")
                    else:
                        section_content.append(item_value)
                elif item_type == 'image':
                    images.append(item)
                    section_content.append(f"[Image: {item.get('alt', 'No description')}]")
                elif item_type == 'table':
                    tables.append(item)
                    section_content.append(f"[Table: {item.get('md', 'No table content')}]")
    
    if started:
        logger.info(f"Ended section '{target}' on page {current_page}. {end_reason}")
        return create_section_dict(section_content, current_page, start_page_num, section_num, images, tables), end_reason
    
    logger.warning(f"Section '{target}' not found")
    return None, "Section not found"

def is_matching_heading(heading, target, alternative_names):
    cleaned_heading = re.sub(r'^\d+(\.\d+)*\s*', '', heading).strip().lower()
    
    if similarity(cleaned_heading, target.lower()) > 0.8:
        return True
    
    for alt_name in alternative_names.get(target, []):
        if similarity(cleaned_heading, alt_name.lower()) > 0.8:
            return True
    
    return False

def extract_section_number(heading):
    match = re.match(r'^(\d+(\.\d+)*)', heading)
    return match.group(1) if match else None

def is_next_main_section(heading, current_section_num, current_target, alternative_names):
    # First, check if the heading is a date
    if is_date(heading):
        return False

    if current_section_num is None:
        # If current section has no number, check if the new heading matches a different main section
        return not is_matching_heading(heading, current_target, alternative_names)
    
    new_section_num = extract_section_number(heading)
    if new_section_num:
        current_main = current_section_num.split('.')[0]
        new_main = new_section_num.split('.')[0]
        return new_main != current_main
    return False

def is_date(string):
    date_patterns = [
        r'\d{1,2}-[A-Z]{3}-\d{4}',  # 29-SEP-2022
        r'\d{1,2}/\d{1,2}/\d{4}',   # 09/29/2022
        r'\d{4}-\d{2}-\d{2}'        # 2022-09-29
    ]
    for pattern in date_patterns:
        if re.match(pattern, string.strip()):
            return True
    return False

def create_section_dict(content, end_page, start_page, section_num, images, tables):
    return {
        "content": '\n\n'.join(content),
        "start_page": start_page,
        "end_page": end_page,
        "section_num": section_num,
        "images": images,
        "tables": tables
    }

def is_toc_page(page_content):
    toc_patterns = [
        r'\d+(\.\d+)*\s+[A-Z].*\.{3,}',  # Numbered section with dots
        r'^(\d+\.?)+\s+',                # Line starting with numbered section
        r'.*\.{10,}\d+$'                 # Line ending with many dots and a number
    ]
    text = ' '.join([item.get('value', '') for item in page_content.get('items', [])])
    return any(re.search(pattern, text, re.MULTILINE) for pattern in toc_patterns)

def identify_toc_pages_pdfminer(pdf_path):
    toc_pages = []
    toc_started = False
    toc_ended = False
    
    def is_toc_line(text):
        return bool(re.search(r'\d+(\.\d+)*\s+[A-Z].*\.{3,}', text)) or \
               bool(re.search(r'^(\d+\.?)+\s+', text)) or \
               ('.' * 10 in text and re.search(r'\d+$', text.strip()))

    for page_layout in extract_pages(pdf_path):
        page_number = page_layout.pageid
        page_text = ""
        
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                page_text += element.get_text()
        
        if not toc_started and "Table of Contents" in page_text:
            toc_started = True
            toc_pages.append(page_number)
            logger.info(f"Detected start of table of contents on page {page_number}")
            continue
        
        if toc_started and not toc_ended:
            if any(is_toc_line(line) for line in page_text.split('\n')):
                toc_pages.append(page_number)
                logger.info(f"Detected table of contents on page {page_number}")
            else:
                toc_ended = True
                logger.info(f"Table of contents ended before page {page_number}")
                break
    
    return toc_pages