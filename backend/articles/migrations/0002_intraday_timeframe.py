# Hourly cards became 4-hour intraday cards. Existing "hour" rows are kept
# (their article URLs keep working) and relabelled; the agent rebuilds any
# still-open block as a full 4-hour card.

from django.db import migrations, models


def hour_to_intraday(apps, schema_editor):
    apps.get_model("articles", "Card").objects.filter(timeframe="hour").update(timeframe="intraday")
    apps.get_model("articles", "CardArticle").objects.filter(time_window="hour").update(time_window="intraday")


def intraday_to_hour(apps, schema_editor):
    apps.get_model("articles", "Card").objects.filter(timeframe="intraday").update(timeframe="hour")
    apps.get_model("articles", "CardArticle").objects.filter(time_window="intraday").update(time_window="hour")


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='card',
            name='timeframe',
            field=models.CharField(choices=[('intraday', 'Intraday (4h)'), ('day', 'Day'), ('week', 'Week'), ('month', 'Month')], max_length=16),
        ),
        migrations.RunPython(hour_to_intraday, intraday_to_hour),
    ]
