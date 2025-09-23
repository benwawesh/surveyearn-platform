# tutorials/management/commands/create_sample_tutorials.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tutorials.models import (
    TutorialCategory, Tutorial, QuizQuestion, QuizAnswer
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Creates sample tutorial data for testing the admin interface'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing tutorial data before creating samples',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing tutorial data...')
            QuizAnswer.objects.all().delete()
            QuizQuestion.objects.all().delete()
            Tutorial.objects.all().delete()
            TutorialCategory.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('✓ Existing data cleared.'))

        # Create Categories
        self.stdout.write('Creating categories...')
        categories_data = [
            {
                'name': 'Getting Started',
                'description': 'Essential tutorials for new users to get started with SurveyEarn',
                'is_active': True
            },
            {
                'name': 'Survey Mastery',
                'description': 'Advanced techniques for maximizing survey earnings and efficiency',
                'is_active': True
            },
            {
                'name': 'Payments & Withdrawals',
                'description': 'Understanding M-Pesa integration and payment processes',
                'is_active': True
            },
            {
                'name': 'Referral Success',
                'description': 'Building and managing your referral network effectively',
                'is_active': True
            },
            {
                'name': 'Platform Features',
                'description': 'Exploring advanced features and tools on SurveyEarn',
                'is_active': True
            }
        ]

        categories = {}
        for cat_data in categories_data:
            category, created = TutorialCategory.objects.get_or_create(
                name=cat_data['name'],
                defaults=cat_data
            )
            categories[cat_data['name']] = category
            if created:
                self.stdout.write(f'  ✓ Created category: {category.name}')

        # Create Tutorials with corrected field names
        self.stdout.write('Creating tutorials...')
        tutorials_data = [
            # Getting Started Category
            {
                'title': 'Welcome to SurveyEarn Platform',
                'category': 'Getting Started',
                'description': 'Your complete introduction to SurveyEarn. Learn how to navigate the platform, understand earning opportunities, and set up your account for maximum success.',
                'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'video_duration': 5,  # Changed from duration_minutes
                'order': 1,
                'completion_reward': 50.00,  # Changed from reward_amount
                'quiz_pass_percentage': 70,
                'max_quiz_attempts': 3,
                'is_published': True,  # Changed from is_active
                'questions': [
                    {
                        'text': 'What is the minimum payout amount on SurveyEarn?',
                        'type': 'multiple_choice',
                        'answers': [
                            {'text': 'KES 100', 'correct': False},
                            {'text': 'KES 200', 'correct': True, 'explanation': 'The minimum payout is KES 200'},
                            {'text': 'KES 500', 'correct': False},
                            {'text': 'KES 50', 'correct': False}
                        ]
                    },
                    {
                        'text': 'Survey earnings are paid instantly after completion.',
                        'type': 'true_false',
                        'answers': [
                            {'text': 'True', 'correct': False,
                             'explanation': 'Payments are processed automatically but may take a few minutes'},
                            {'text': 'False', 'correct': True,
                             'explanation': 'Correct! Payments are processed automatically but not instantly'}
                        ]
                    }
                ]
            },
            {
                'title': 'Creating Your Profile',
                'category': 'Getting Started',
                'description': 'Complete your profile to unlock more survey opportunities and higher earnings.',
                'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'video_duration': 8,
                'order': 2,
                'completion_reward': 75.00,
                'quiz_pass_percentage': 80,
                'max_quiz_attempts': 3,
                'is_published': True,
                'questions': [
                    {
                        'text': 'Why is completing your profile important?',
                        'type': 'multiple_choice',
                        'answers': [
                            {'text': 'It looks nice', 'correct': False},
                            {'text': 'It helps match you with relevant surveys', 'correct': True,
                             'explanation': 'A complete profile helps us send you surveys that match your demographics'},
                            {'text': 'It is required by law', 'correct': False},
                            {'text': 'It has no benefit', 'correct': False}
                        ]
                    }
                ]
            },
            {
                'title': 'Maximizing Survey Earnings',
                'category': 'Survey Mastery',
                'description': 'Advanced tips and tricks to increase your survey completion rate and earnings.',
                'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'video_duration': 12,
                'order': 1,
                'completion_reward': 100.00,
                'quiz_pass_percentage': 75,
                'max_quiz_attempts': 2,
                'is_published': True,
                'questions': [
                    {
                        'text': 'What should you do if you encounter technical issues during a survey?',
                        'type': 'multiple_choice',
                        'answers': [
                            {'text': 'Close the browser and try later', 'correct': False},
                            {'text': 'Contact support immediately', 'correct': True,
                             'explanation': 'Always contact support for technical issues to ensure you get credited'},
                            {'text': 'Refresh the page multiple times', 'correct': False},
                            {'text': 'Skip the survey completely', 'correct': False}
                        ]
                    }
                ]
            },
            {
                'title': 'Understanding M-Pesa Payments',
                'category': 'Payments & Withdrawals',
                'description': 'Learn how our M-Pesa integration works and how to troubleshoot payment issues.',
                'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'video_duration': 10,
                'order': 1,
                'completion_reward': 80.00,
                'quiz_pass_percentage': 80,
                'max_quiz_attempts': 3,
                'is_published': True,
                'questions': [
                    {
                        'text': 'What information do you need to provide for M-Pesa payments?',
                        'type': 'multiple_choice',
                        'answers': [
                            {'text': 'Only your phone number', 'correct': True,
                             'explanation': 'Your registered M-Pesa phone number is all we need'},
                            {'text': 'Phone number and PIN', 'correct': False},
                            {'text': 'Full name and ID number', 'correct': False},
                            {'text': 'Bank account details', 'correct': False}
                        ]
                    }
                ]
            },
            {
                'title': 'Building Your Referral Network',
                'category': 'Referral Success',
                'description': 'Master the art of referrals and create a sustainable income stream.',
                'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'video_duration': 15,
                'order': 1,
                'completion_reward': 150.00,
                'quiz_pass_percentage': 85,
                'max_quiz_attempts': 2,
                'is_published': True,
                'questions': [
                    {
                        'text': 'What percentage commission do you earn from direct referrals?',
                        'type': 'multiple_choice',
                        'answers': [
                            {'text': '5%', 'correct': False},
                            {'text': '10%', 'correct': True,
                             'explanation': 'You earn 10% commission from your direct referrals'},
                            {'text': '15%', 'correct': False},
                            {'text': '20%', 'correct': False}
                        ]
                    }
                ]
            }
        ]

        # Create tutorials and their questions
        tutorial_objects = []
        for tutorial_data in tutorials_data:
            questions_data = tutorial_data.pop('questions', [])
            category_name = tutorial_data.pop('category')
            tutorial_data['category'] = categories[category_name]

            tutorial, created = Tutorial.objects.get_or_create(
                title=tutorial_data['title'],
                defaults=tutorial_data
            )
            tutorial_objects.append(tutorial)

            if created:
                self.stdout.write(f'  ✓ Created tutorial: {tutorial.title}')

                # Create questions for this tutorial
                for i, question_data in enumerate(questions_data, 1):
                    answers_data = question_data.pop('answers', [])
                    question_data['tutorial'] = tutorial
                    question_data['order'] = i
                    question_data['question_text'] = question_data.pop('text')
                    question_data['question_type'] = question_data.pop('type')

                    question = QuizQuestion.objects.create(**question_data)
                    self.stdout.write(f'    ✓ Created question: {question.question_text[:50]}...')

                    # Create answers for this question
                    for answer_data in answers_data:
                        answer_data['question'] = question
                        answer_data['answer_text'] = answer_data.pop('text')
                        answer_data['is_correct'] = answer_data.pop('correct')

                        answer = QuizAnswer.objects.create(**answer_data)

        # Set prerequisites (tutorial 2 requires tutorial 1, etc.)
        if len(tutorial_objects) > 1:
            tutorial_objects[1].prerequisites.add(tutorial_objects[0])
            self.stdout.write('✓ Set prerequisites for "Creating Your Profile"')

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {len(categories)} categories and {len(tutorial_objects)} tutorials with questions!'
            )
        )