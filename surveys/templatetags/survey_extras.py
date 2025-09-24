from django import template
from django.db.models import Avg
from surveys.models import Answer

register = template.Library()


@register.filter
def average_rating(question):
    """
    Calculate the average rating for a rating question.
    Returns the average rating value or 0 if no ratings exist.
    """
    if question.question_type != 'rating':
        return 0

    # Get all rating answers for this question
    avg_rating = Answer.objects.filter(
        question=question,
        rating_answer__isnull=False
    ).aggregate(avg=Avg('rating_answer'))['avg']

    return avg_rating if avg_rating is not None else 0


@register.filter
def response_count(question):
    """
    Get the number of responses for a specific question.
    """
    return Answer.objects.filter(question=question).count()


@register.filter
def correct_answers_count(question):
    """
    Count how many users answered a question correctly.
    Only works for MCQ, checkbox, and yes_no questions.
    """
    if question.question_type not in ['mcq', 'checkbox', 'yes_no']:
        return 0

    correct_count = 0

    # Get all responses for this question
    answers = Answer.objects.filter(question=question)

    for answer in answers:
        if question.question_type == 'mcq':
            # For MCQ, check if selected choice is correct
            if answer.choice_answer and answer.choice_answer.is_correct:
                correct_count += 1

        elif question.question_type == 'checkbox':
            # For checkbox, check if all selected choices match correct ones
            if answer.checkbox_answers.exists():
                selected_choices = set(answer.checkbox_answers.all())
                correct_choices = set(question.choices.filter(is_correct=True))
                if selected_choices == correct_choices:
                    correct_count += 1

        elif question.question_type == 'yes_no':
            # For yes/no, check if boolean answer matches correct choice
            correct_choice = question.choices.filter(is_correct=True).first()
            if correct_choice and answer.boolean_answer is not None:
                # Assuming 'Yes' choice text means True, 'No' means False
                expected_answer = correct_choice.choice_text.lower() == 'yes'
                if answer.boolean_answer == expected_answer:
                    correct_count += 1

    return correct_count


@register.filter
def percentage(part, whole):
    """
    Calculate percentage. Returns 0 if whole is 0 or None.
    """
    if not whole or whole == 0:
        return 0
    return (part / whole) * 100


# Additional template tags needed for survey forms
@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a dynamic key"""
    if dictionary:
        return dictionary.get(str(key))
    return None


@register.filter
def get_list_item(dictionary, key):
    """Get a list item from a dictionary using a dynamic key"""
    if dictionary:
        return dictionary.getlist(str(key))
    return []


@register.simple_tag
def get_form_value(form_data, field_name):
    """Get form value by field name"""
    if form_data:
        return form_data.get(field_name, '')
    return ''


@register.filter
def add(value1, value2):
    """Concatenate two strings or add two numbers"""
    try:
        # Try numeric addition first
        return float(value1) + float(value2)
    except (ValueError, TypeError):
        # Fall back to string concatenation
        return str(value1) + str(value2)