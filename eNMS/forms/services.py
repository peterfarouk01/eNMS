from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, SelectField, StringField
from wtforms.widgets import TextArea

from eNMS.forms import metaform
from eNMS.forms.fields import DictField


class ValidationForm(FlaskForm, metaclass=metaform):
    form_type = HiddenField(default="service_validation")
    abstract_service = True
    validation_method = SelectField(
        choices=(
            ("text", "Validation by text match"),
            ("dict_equal", "Validation by dictionary equality"),
            ("dict_included", "Validation by dictionary inclusion"),
        )
    )
    content_match = StringField(widget=TextArea(), render_kw={"rows": 5})
    content_match_regex = BooleanField()
    dict_match = DictField()
    negative_logic = BooleanField()
    delete_spaces_before_matching = BooleanField()