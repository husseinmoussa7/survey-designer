# server/app.py
import sys
import os
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
import pandas as pd
import json
import tempfile
from io import StringIO

import pipeline.flow as survey_logic

load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='')


def set_api_keys(api_keys_dict):
    os.environ['QUALTRICS_API_TOKEN']     = api_keys_dict.get('qualtricsApiToken', '')
    os.environ['QUALTRICS_DATA_CENTER']   = api_keys_dict.get('qualtricsDataCenter', '')
    os.environ['AWS_ACCESS_KEY_ID']       = api_keys_dict.get('awsAccessKeyId', '')
    os.environ['AWS_SECRET_ACCESS_KEY']   = api_keys_dict.get('awsSecretAccessKey', '')
    os.environ['OPENAI_API_KEY']          = api_keys_dict.get('openaiApiKey', '')
    os.environ['ANTHROPIC_API_KEY']       = api_keys_dict.get('anthropicApiKey', '')


def restructure_data_for_debias(simulated_df, survey_context_dict):
    questions = survey_context_dict.get('revised_survey', survey_context_dict).get('questions', [])
    pipeline_input_data = []
    for i, q_data in enumerate(questions):
        answer_col_name = f"Q{i + 1}"
        if answer_col_name in simulated_df.columns:
            pipeline_input_data.append({
                "Question":  q_data["question_text"],
                "llm_resp":  simulated_df[answer_col_name].tolist()
            })
    return pipeline_input_data


@app.route('/')
def index():
    return send_from_directory('static', 'survey.html')


@app.route('/api/process-survey', methods=['POST'])
def process_survey():
    data = request.json
    set_api_keys(data.get('apiKeys', {}))
    survey_text = data.get('surveyText')
    if not survey_text:
        return jsonify({"error": "Survey text is required."}), 400
    try:
        flow = survey_logic.SurveyEnhancementFlow()
        initial_survey = flow.run(survey_text)
        return jsonify({"survey": initial_survey})
    except Exception as e:
        print(f"Error in /api/process-survey: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/enhance-survey', methods=['POST'])
def enhance_survey():
    data = request.json
    set_api_keys(data.get('apiKeys', {}))
    survey_dict = data.get('survey')
    feedback    = data.get('feedback')
    if not survey_dict or not feedback:
        return jsonify({"error": "Survey and feedback are required."}), 400
    try:
        flow = survey_logic.SurveyEnhancementFlow()
        flow.enhanced_dict = survey_dict
        enhanced_survey = flow.run_single_enhancement_cycle(feedback)
        return jsonify({"enhancedSurvey": enhanced_survey})
    except Exception as e:
        print(f"Error in /api/enhance-survey: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/deploy', methods=['POST'])
def deploy_survey():
    data     = request.json
    api_keys = data.get('apiKeys', {})
    set_api_keys(api_keys)
    survey_dict = data.get('survey')
    use_mturk   = data.get('useMturk', False)
    mturk_config_frontend = data.get('mturkConfig', {})
    if not survey_dict:
        return jsonify({"error": "Survey data is required for deployment."}), 400
    try:
        use_sandbox  = api_keys.get('mturkSandbox') == 'True'
        mturk_client = survey_logic.MTurkClient(use_sandbox=use_sandbox)
        automation   = survey_logic.QualtricsAndMTurkAutomation(mturk_client=mturk_client)
        qualtrics_payload = survey_logic.survey_dict_to_qualtrics_payload(survey_dict)
        if use_mturk:
            survey_meta = survey_dict.get("revised_survey", {})
            hit_config  = {
                'Title':       f'Complete a survey on {survey_meta.get("theme", "research topic")}',
                'Description': survey_meta.get("purpose", "Complete a short research survey"),
                'Keywords':    'survey, research, feedback',
                'Reward':      mturk_config_frontend.get('Reward', '0.75'),
                'MaxAssignments':             int(mturk_config_frontend.get('MaxAssignments', 100)),
                'LifetimeInSeconds':          86400,
                'AssignmentDurationInSeconds': 1800,
                'AutoApprovalDelayInSeconds': 86400,
                'QualificationRequirements':  []
            }
            results = automation.run(qualtrics_payload, hit_config)
            return jsonify({
                "surveyLink": results.get('survey_link'),
                "surveyId":   results.get('survey_id'),
                "hitId":      results.get('hit_id')
            })
        else:
            survey_id, survey_link = automation.deploy_to_qualtrics_only(qualtrics_payload)
            return jsonify({"surveyLink": survey_link, "surveyId": survey_id})
    except Exception as e:
        print(f"Error in /api/deploy: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/collect-data', methods=['POST'])
def collect_data():
    data     = request.json
    api_keys = data.get('apiKeys', {})
    set_api_keys(api_keys)
    survey_id = data.get('surveyId')
    hit_id    = data.get('hitId')
    if not survey_id:
        return jsonify({"error": "Qualtrics Survey ID is required."}), 400
    try:
        use_sandbox = api_keys.get('mturkSandbox') == 'True'
        automation  = survey_logic.QualtricsAndMTurkAutomation(
            mturk_client=survey_logic.MTurkClient(use_sandbox=use_sandbox)
        )
        results   = automation.collect_and_process_results(survey_id, hit_id)
        data_json = results['responses'].to_dict(orient='records')
        return jsonify({"data": data_json})
    except Exception as e:
        print(f"Error in /api/collect-data: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/simulate-data', methods=['POST'])
def simulate_data():
    data = request.json
    set_api_keys(data.get('apiKeys', {}))
    try:
        temp_template_path    = "temp_survey_response_template.txt"
        temp_context_path     = "temp_test_survey.json"
        temp_participants_path = "temp_participant_pool.csv"
        with open(temp_template_path, "w") as f:
            f.write(data.get('template', ''))
        with open(temp_context_path, "w") as f:
            f.write(data.get('surveyContext', ''))
        with open(temp_participants_path, "w") as f:
            f.write(data.get('participants', ''))
        output_df = survey_logic.collect_simulated_data(
            template_path=temp_template_path,
            survey_context_path=temp_context_path,
            participant_csv_path=temp_participants_path
        )
        os.remove(temp_template_path)
        os.remove(temp_context_path)
        os.remove(temp_participants_path)
        return jsonify({"simulationOutput": output_df.to_json(orient='records')})
    except Exception as e:
        print(f"Error in /api/simulate-data: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/debias-data', methods=['POST'])
def debias_data():
    try:
        data = request.json
        set_api_keys(data.get('apiKeys', {}))
        simulated_data_json = data.get('simulatedData')
        survey_context_str  = data.get('surveyContext')
        if not simulated_data_json:
            return jsonify({"error": "Simulated data is required."}), 400
        if not survey_context_str:
            return jsonify({"error": "Survey context is required."}), 400
        simulated_df     = pd.read_json(StringIO(simulated_data_json), orient='records')
        survey_context_dict = json.loads(survey_context_str)
        restructured_data = restructure_data_for_debias(simulated_df, survey_context_dict)
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json', encoding='utf-8') as tmp_in, \
             tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json', encoding='utf-8') as tmp_out:
            input_filepath  = tmp_in.name
            output_filepath = tmp_out.name
            json.dump(restructured_data, tmp_in, indent=4)
            tmp_in.flush()
            survey_logic.run_debias_pipeline(input_json=input_filepath, output_json=output_filepath)
            with open(output_filepath, 'r', encoding='utf-8') as f:
                debiased_data = json.load(f)
            os.unlink(input_filepath)
            os.unlink(output_filepath)
            debiased_df = pd.DataFrame(debiased_data)
        return jsonify({"debiasedOutput": debiased_df.to_json(orient='records')})
    except Exception as e:
        print(f"Error in /api/debias-data: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/generate-paper', methods=['POST'])
def generate_paper():
    data = request.json
    set_api_keys(data.get('apiKeys', {}))
    csv_data   = data.get('csvData')
    hypothesis = data.get('hypothesis')
    if not csv_data:
        return jsonify({"error": "CSV data is required."}), 400
    temp_csv_path = "temp_paper_data.csv"
    try:
        with open(temp_csv_path, "w", encoding="utf-8") as f:
            f.write(csv_data)
        paper_markdown = survey_logic.generate_research_paper(
            csv_path=temp_csv_path, hypothesis=hypothesis
        )
        os.remove(temp_csv_path)
        return jsonify({"paperMarkdown": paper_markdown})
    except Exception as e:
        print(f"Error in /api/generate-paper: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)
