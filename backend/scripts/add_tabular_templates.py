#!/usr/bin/env python3
"""Script to add default tabular review templates to the database"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import get_db
from app.models.tabular_review import TabularColumnTemplate
from datetime import datetime

# Default templates for Russian legal practice
DEFAULT_TEMPLATES = [
    {
        "name": "NDA Review (template)",
        "description": "A boilerplate review for NDAs (covering the most common review areas of non-disclosure agreements).",
        "category": "contract",
        "tags": ["Law firm", "In-house"],
        "is_system": True,
        "is_public": True,
        "is_featured": True,
        "columns": [
            {
                "column_label": "Parties",
                "column_type": "text",
                "prompt": "Who are the parties to this NDA? List all parties involved."
            },
            {
                "column_label": "Start Date",
                "column_type": "date",
                "prompt": "What is the effective date or start date of this NDA?"
            },
            {
                "column_label": "Purpose",
                "column_type": "text",
                "prompt": "What is the purpose of this NDA? What information is being protected?"
            },
            {
                "column_label": "Definition of Confidential Information",
                "column_type": "text",
                "prompt": "How is confidential information defined in this NDA?"
            },
            {
                "column_label": "Term",
                "column_type": "text",
                "prompt": "What is the duration of the confidentiality obligations? Include any post-termination periods."
            },
            {
                "column_label": "Exceptions to Confidentiality",
                "column_type": "text",
                "prompt": "What are the exceptions to confidentiality obligations? List all exceptions."
            },
            {
                "column_label": "Return of Materials",
                "column_type": "yes_no",
                "prompt": "Does this NDA require return or destruction of confidential materials upon termination?"
            },
            {
                "column_label": "Remedies",
                "column_type": "text",
                "prompt": "What remedies are available for breach of confidentiality? Include injunctive relief, damages, etc."
            },
            {
                "column_label": "Governing Law",
                "column_type": "text",
                "prompt": "What is the governing law and jurisdiction for this NDA?"
            },
            {
                "column_label": "Termination",
                "column_type": "text",
                "prompt": "How can this NDA be terminated? What are the termination provisions?"
            }
        ]
    },
    {
        "name": "SPA Review (template)",
        "description": "Template for reviewing Sale and Purchase Agreements (SPAs).",
        "category": "contract",
        "tags": ["Law firm", "M&A"],
        "is_system": True,
        "is_public": True,
        "is_featured": True,
        "columns": [
            {
                "column_label": "Parties",
                "column_type": "text",
                "prompt": "Who are the buyer and seller parties in this SPA?"
            },
            {
                "column_label": "Pricing mechanism",
                "column_type": "text",
                "prompt": "What is the pricing mechanism? Is it locked box, completion accounts, or other?"
            },
            {
                "column_label": "Purchase Price",
                "column_type": "currency",
                "prompt": "What is the purchase price? Include currency and any adjustments."
            },
            {
                "column_label": "Adjustments",
                "column_type": "text",
                "prompt": "What purchase price adjustments are specified? Include working capital, debt, cash adjustments."
            },
            {
                "column_label": "Closing Date",
                "column_type": "date",
                "prompt": "What is the closing date or expected closing date?"
            },
            {
                "column_label": "Shares Acquired",
                "column_type": "number",
                "prompt": "How many shares are being acquired? What percentage of the company?"
            },
            {
                "column_label": "Conditions Precedent",
                "column_type": "text",
                "prompt": "What are the conditions precedent to closing? List all conditions."
            },
            {
                "column_label": "Representations and Warranties",
                "column_type": "text",
                "prompt": "What are the key representations and warranties? Summarize the main categories."
            },
            {
                "column_label": "Indemnification",
                "column_type": "text",
                "prompt": "What are the indemnification provisions? Include caps, baskets, and survival periods."
            },
            {
                "column_label": "Governing Law",
                "column_type": "text",
                "prompt": "What is the governing law and jurisdiction for this SPA?"
            }
        ]
    },
    {
        "name": "Board meeting minutes",
        "description": "Use this template to review board meeting minutes.",
        "category": "compliance",
        "tags": ["Law firm", "In-house"],
        "is_system": True,
        "is_public": True,
        "is_featured": True,
        "columns": [
            {
                "column_label": "Date",
                "column_type": "date",
                "prompt": "What is the date of this board meeting?"
            },
            {
                "column_label": "Location",
                "column_type": "text",
                "prompt": "Where was this board meeting held?"
            },
            {
                "column_label": "Meeting minutes",
                "column_type": "text",
                "prompt": "What are the key topics discussed in this meeting? Summarize the main agenda items."
            },
            {
                "column_label": "Attendees",
                "column_type": "text",
                "prompt": "Who attended this board meeting? List all attendees."
            },
            {
                "column_label": "Resolutions",
                "column_type": "text",
                "prompt": "What resolutions were passed at this meeting? List all resolutions."
            },
            {
                "column_label": "Action Items",
                "column_type": "text",
                "prompt": "What action items were assigned? List all action items with responsible parties."
            }
        ]
    },
    {
        "name": "Loan Agreement Analysis",
        "description": "Template for analyzing loan agreements and credit facilities.",
        "category": "contract",
        "tags": ["Law firm", "Finance"],
        "is_system": True,
        "is_public": True,
        "is_featured": False,
        "columns": [
            {
                "column_label": "Loan Type",
                "column_type": "text",
                "prompt": "What type of loan is this? (e.g., term loan, revolving credit, bridge loan)"
            },
            {
                "column_label": "Principal Amount",
                "column_type": "currency",
                "prompt": "What is the principal loan amount? Include currency."
            },
            {
                "column_label": "Interest Rate",
                "column_type": "text",
                "prompt": "What is the interest rate? Include fixed/variable, margin, and base rate."
            },
            {
                "column_label": "Term",
                "column_type": "text",
                "prompt": "What is the loan term? Include maturity date and any renewal options."
            },
            {
                "column_label": "Payment Schedule",
                "column_type": "text",
                "prompt": "What is the payment schedule? Include frequency and amounts."
            },
            {
                "column_label": "Security",
                "column_type": "text",
                "prompt": "What security or collateral is provided for this loan?"
            },
            {
                "column_label": "Covenants",
                "column_type": "text",
                "prompt": "What are the key financial and non-financial covenants?"
            },
            {
                "column_label": "Events of Default",
                "column_type": "text",
                "prompt": "What are the events of default? List all events."
            },
            {
                "column_label": "Prepayment",
                "column_type": "text",
                "prompt": "What are the prepayment provisions? Include any penalties or restrictions."
            }
        ]
    },
    {
        "name": "Employment Agreement Review",
        "description": "Template for reviewing employment agreements and contracts.",
        "category": "contract",
        "tags": ["Law firm", "In-house", "HR"],
        "is_system": True,
        "is_public": True,
        "is_featured": False,
        "columns": [
            {
                "column_label": "Employee Name",
                "column_type": "text",
                "prompt": "Who is the employee? What is their name and position?"
            },
            {
                "column_label": "Start Date",
                "column_type": "date",
                "prompt": "What is the employment start date?"
            },
            {
                "column_label": "Salary",
                "column_type": "currency",
                "prompt": "What is the base salary? Include currency and payment frequency."
            },
            {
                "column_label": "Bonus",
                "column_type": "text",
                "prompt": "What are the bonus provisions? Include eligibility and calculation method."
            },
            {
                "column_label": "Term",
                "column_type": "text",
                "prompt": "What is the employment term? Is it fixed-term or indefinite?"
            },
            {
                "column_label": "Notice Period",
                "column_type": "text",
                "prompt": "What is the notice period for termination? Include both employer and employee notice."
            },
            {
                "column_label": "Non-compete",
                "column_type": "yes_no",
                "prompt": "Does this agreement contain a non-compete clause?"
            },
            {
                "column_label": "Non-compete Terms",
                "column_type": "text",
                "prompt": "If there is a non-compete clause, what are its terms? Include duration, geographic scope, and restrictions."
            },
            {
                "column_label": "Confidentiality",
                "column_type": "yes_no",
                "prompt": "Does this agreement contain confidentiality obligations?"
            },
            {
                "column_label": "Intellectual Property",
                "column_type": "text",
                "prompt": "Who owns intellectual property created during employment? What are the IP assignment provisions?"
            }
        ]
    },
    {
        "name": "Data Processing Agreement (DPA)",
        "description": "Template for reviewing Data Processing Agreements under GDPR and Russian data protection laws.",
        "category": "compliance",
        "tags": ["Law firm", "In-house", "Privacy"],
        "is_system": True,
        "is_public": True,
        "is_featured": False,
        "columns": [
            {
                "column_label": "Parties",
                "column_type": "text",
                "prompt": "Who are the data controller and data processor parties?"
            },
            {
                "column_label": "Subject Matter",
                "column_type": "text",
                "prompt": "What is the subject matter of the data processing? What personal data is being processed?"
            },
            {
                "column_label": "Duration",
                "column_type": "text",
                "prompt": "What is the duration of the processing? Include start date and termination provisions."
            },
            {
                "column_label": "Nature and Purpose",
                "column_type": "text",
                "prompt": "What is the nature and purpose of the processing? What are the processing activities?"
            },
            {
                "column_label": "Data Subject Categories",
                "column_type": "text",
                "prompt": "What categories of data subjects are covered? (e.g., employees, customers, etc.)"
            },
            {
                "column_label": "Personal Data Categories",
                "column_type": "text",
                "prompt": "What categories of personal data are processed? (e.g., names, email addresses, etc.)"
            },
            {
                "column_label": "Security Measures",
                "column_type": "text",
                "prompt": "What security measures are required? List all technical and organizational measures."
            },
            {
                "column_label": "Sub-processors",
                "column_type": "text",
                "prompt": "What are the provisions regarding sub-processors? Include consent requirements and notification obligations."
            },
            {
                "column_label": "Data Subject Rights",
                "column_type": "text",
                "prompt": "How are data subject rights handled? What are the processor's obligations?"
            },
            {
                "column_label": "Data Breach",
                "column_type": "text",
                "prompt": "What are the data breach notification requirements? Include timing and content requirements."
            },
            {
                "column_label": "Data Return/Deletion",
                "column_type": "text",
                "prompt": "What are the provisions for return or deletion of data after termination?"
            },
            {
                "column_label": "Audit Rights",
                "column_type": "yes_no",
                "prompt": "Does the controller have audit rights? Can they inspect the processor's facilities?"
            }
        ]
    },
    {
        "name": "Distribution Agreement Review",
        "description": "Boilerplate Distribution Agreement review template for Tabular Review.",
        "category": "contract",
        "tags": ["Law firm", "Commercial"],
        "is_system": True,
        "is_public": True,
        "is_featured": False,
        "columns": [
            {
                "column_label": "Parties",
                "column_type": "text",
                "prompt": "Who are the supplier and distributor parties?"
            },
            {
                "column_label": "Geographical Territory",
                "column_type": "text",
                "prompt": "What is the geographical territory for distribution? Include any restrictions."
            },
            {
                "column_label": "Exclusivity Clause",
                "column_type": "text",
                "prompt": "Is this an exclusive or non-exclusive distribution agreement? What are the exclusivity terms?"
            },
            {
                "column_label": "Products",
                "column_type": "text",
                "prompt": "What products are covered by this distribution agreement?"
            },
            {
                "column_label": "Pricing",
                "column_type": "text",
                "prompt": "What are the pricing terms? Include purchase prices, discounts, and payment terms."
            },
            {
                "column_label": "Minimum Purchase Requirements",
                "column_type": "text",
                "prompt": "Are there minimum purchase requirements? Include quantities and time periods."
            },
            {
                "column_label": "Term",
                "column_type": "text",
                "prompt": "What is the term of this agreement? Include start date, duration, and renewal provisions."
            },
            {
                "column_label": "Termination",
                "column_type": "text",
                "prompt": "How can this agreement be terminated? Include termination events and notice requirements."
            },
            {
                "column_label": "Restrictions",
                "column_type": "text",
                "prompt": "What restrictions are placed on the distributor? Include competitive restrictions, territory limitations, etc."
            }
        ]
    }
]

def add_default_templates():
    """Add default templates to database"""
    db = next(get_db())
    
    try:
        # Check if templates already exist
        existing = db.query(TabularColumnTemplate).filter(
            TabularColumnTemplate.is_system == True
        ).count()
        
        if existing > 0:
            print(f"Found {existing} existing system templates. Skipping insertion.")
            return
        
        # Add all templates
        for template_data in DEFAULT_TEMPLATES:
            template = TabularColumnTemplate(
                user_id=None,  # System templates have no user
                name=template_data["name"],
                description=template_data["description"],
                columns=template_data["columns"],
                is_public=template_data["is_public"],
                is_system=template_data["is_system"],
                is_featured=template_data["is_featured"],
                category=template_data["category"],
                tags=template_data["tags"],
                usage_count=0,
                created_at=datetime.utcnow()
            )
            db.add(template)
        
        db.commit()
        print(f"Successfully added {len(DEFAULT_TEMPLATES)} default templates to database")
        
    except Exception as e:
        db.rollback()
        print(f"Error adding templates: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    add_default_templates()

