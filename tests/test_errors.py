import json
import logging

import pytest

from flask import Blueprint, abort
from flask.signals import got_request_exception

from werkzeug.exceptions import HTTPException, BadRequest, NotFound, Aborter
from werkzeug.http import quote_etag, unquote_etag

import flask_restx as restx


class ErrorsTest(object):
    def test_abort_type(self):
        with pytest.raises(HTTPException):
            restx.abort(404)

    def test_abort_data(self):
        with pytest.raises(HTTPException) as cm:
            restx.abort(404, foo="bar")
        assert cm.value.data == {"foo": "bar"}

    def test_abort_no_data(self):
        with pytest.raises(HTTPException) as cm:
            restx.abort(404)
        assert not hasattr(cm.value, "data")

    def test_abort_custom_message(self):
        with pytest.raises(HTTPException) as cm:
            restx.abort(404, "My message")
        assert cm.value.data["message"] == "My message"

    def test_abort_code_only_with_defaults(self, app, client):
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                api.abort(403)

        response = client.get("/test/")
        assert response.status_code == 403
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert "message" in data

    def test_abort_with_message(self, app, client):
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                api.abort(403, "A message")

        response = client.get("/test/")
        assert response.status_code == 403
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data["message"] == "A message"

    def test_abort_with_lazy_init(self, app, client):
        api = restx.Api()

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                api.abort(403)

        api.init_app(app)

        response = client.get("/test/")
        assert response.status_code == 403
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert "message" in data

    def test_abort_on_exception(self, app, client):
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise ValueError()

        response = client.get("/test/")
        assert response.status_code == 500
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert "message" in data

    def test_abort_on_exception_with_lazy_init(self, app, client):
        api = restx.Api()

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise ValueError()

        api.init_app(app)

        response = client.get("/test/")
        assert response.status_code == 500
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert "message" in data

    def test_errorhandler_for_exception_inheritance(self, app, client):
        api = restx.Api(app)

        class CustomException(RuntimeError):
            pass

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @api.errorhandler(RuntimeError)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_errorhandler_for_custom_exception(self, app, client):
        api = restx.Api(app)

        class CustomException(RuntimeError):
            pass

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @api.errorhandler(CustomException)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_blunder_in_errorhandler_is_not_suppressed_in_logs(
        self, app, client, caplog
    ):
        api = restx.Api(app)

        class CustomException(RuntimeError):
            pass

        class ProgrammingBlunder(Exception):
            pass

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @api.errorhandler(CustomException)
        def handle_custom_exception(error):
            raise ProgrammingBlunder(
                "This exception needs to be logged, not suppressed, then cause 500"
            )

        with caplog.at_level(logging.ERROR):
            response = client.get("/test/")
        exc_type, value, traceback = caplog.records[0].exc_info
        assert exc_type is ProgrammingBlunder
        assert response.status_code == 500

    def test_errorhandler_for_custom_exception_with_headers(self, app, client):
        api = restx.Api(app)

        class CustomException(RuntimeError):
            pass

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @api.errorhandler(CustomException)
        def handle_custom_exception(error):
            return {"message": "some maintenance"}, 503, {"Retry-After": 120}

        response = client.get("/test/")
        assert response.status_code == 503
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {"message": "some maintenance"}
        assert response.headers["Retry-After"] == "120"

    def test_errorhandler_for_httpexception(self, app, client):
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise BadRequest()

        @api.errorhandler(BadRequest)
        def handle_badrequest_exception(error):
            return {"message": str(error), "test": "value"}, 400

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": str(BadRequest()),
            "test": "value",
        }

    def test_errorhandler_with_namespace(self, app, client):
        api = restx.Api(app)

        ns = restx.Namespace("ExceptionHandler", path="/")

        class CustomException(RuntimeError):
            pass

        @ns.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @ns.errorhandler(CustomException)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        api.add_namespace(ns)

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_errorhandler_with_namespace_from_api(self, app, client):
        api = restx.Api(app)

        ns = api.namespace("ExceptionHandler", path="/")

        class CustomException(RuntimeError):
            pass

        @ns.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @ns.errorhandler(CustomException)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_default_errorhandler(self, app, client):
        api = restx.Api(app)

        @api.route("/test/")
        class TestResource(restx.Resource):
            def get(self):
                raise Exception("error")

        response = client.get("/test/")
        assert response.status_code == 500
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert "message" in data

    def test_default_errorhandler_with_propagate_true(self, app, client):
        blueprint = Blueprint("api", __name__, url_prefix="/api")
        api = restx.Api(blueprint)

        @api.route("/test/")
        class TestResource(restx.Resource):
            def get(self):
                raise Exception("error")

        app.register_blueprint(blueprint)

        app.config["PROPAGATE_EXCEPTIONS"] = True

        # From the Flask docs:
        # PROPAGATE_EXCEPTIONS
        # Exceptions are re-raised rather than being handled by the app’s error handlers.
        # If not set, this is implicitly true if TESTING or DEBUG is enabled.
        with pytest.raises(Exception):
            client.get("/api/test/")

    def test_default_errorhandler_with_propagate_not_set_but_testing(self, app, client):
        blueprint = Blueprint("api", __name__, url_prefix="/api")
        api = restx.Api(blueprint)

        @api.route("/test/")
        class TestResource(restx.Resource):
            def get(self):
                raise Exception("error")

        app.register_blueprint(blueprint)

        app.config["PROPAGATE_EXCEPTIONS"] = None
        app.testing = True

        # From the Flask docs:
        # PROPAGATE_EXCEPTIONS
        # Exceptions are re-raised rather than being handled by the app’s error handlers.
        # If not set, this is implicitly true if TESTING or DEBUG is enabled.
        with pytest.raises(Exception):
            client.get("/api/test/")

    def test_default_errorhandler_with_propagate_not_set_but_debug(self, app, client):
        blueprint = Blueprint("api", __name__, url_prefix="/api")
        api = restx.Api(blueprint)

        @api.route("/test/")
        class TestResource(restx.Resource):
            def get(self):
                raise Exception("error")

        app.register_blueprint(blueprint)

        app.config["PROPAGATE_EXCEPTIONS"] = None
        app.debug = True

        # From the Flask docs:
        # PROPAGATE_EXCEPTIONS
        # Exceptions are re-raised rather than being handled by the app’s error handlers.
        # If not set, this is implicitly true if TESTING or DEBUG is enabled.
        with pytest.raises(Exception):
            client.get("/api/test/")

    def test_custom_default_errorhandler(self, app, client):
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise Exception("error")

        @api.errorhandler
        def default_error_handler(error):
            return {"message": str(error), "test": "value"}, 500

        response = client.get("/test/")
        assert response.status_code == 500
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_custom_default_errorhandler_with_headers(self, app, client):
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise Exception("error")

        @api.errorhandler
        def default_error_handler(error):
            return {"message": "some maintenance"}, 503, {"Retry-After": 120}

        response = client.get("/test/")
        assert response.status_code == 503
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {"message": "some maintenance"}
        assert response.headers["Retry-After"] == "120"

    def test_errorhandler_lazy(self, app, client):
        api = restx.Api()

        class CustomException(RuntimeError):
            pass

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise CustomException("error")

        @api.errorhandler(CustomException)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        api.init_app(app)

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_handle_api_error(self, app, client):
        api = restx.Api(app)

        @api.route("/api", endpoint="api")
        class Test(restx.Resource):
            def get(self):
                abort(404)

        response = client.get("/api")
        assert response.status_code == 404
        assert response.headers["Content-Type"] == "application/json"
        data = json.loads(response.data.decode())
        assert "message" in data

    def test_handle_non_api_error(self, app, client):
        restx.Api(app)

        response = client.get("/foo")
        assert response.status_code == 404
        assert response.headers["Content-Type"] == "text/html; charset=utf-8"

    def test_non_api_error_404_catchall(self, app, client):
        api = restx.Api(app, catch_all_404s=True)

        response = client.get("/foo")
        assert response.headers["Content-Type"] == api.default_mediatype

    def test_handle_error_signal(self, app):
        api = restx.Api(app)

        exception = BadRequest()

        recorded = []

        def record(sender, exception):
            recorded.append(exception)

        got_request_exception.connect(record, app)
        try:
            # with self.app.test_request_context("/foo"):
            api.handle_error(exception)
            assert len(recorded) == 1
            assert exception is recorded[0]
        finally:
            got_request_exception.disconnect(record, app)

    def test_handle_error_signal_does_not_call_got_request_exception(self, app):
        api = restx.Api(app)

        exception = BadRequest()

        recorded = []

        def record(sender, exception):
            recorded.append(exception)

        @api.errorhandler(BadRequest)
        def handle_bad_request(error):
            return {"message": str(error), "value": "test"}, 400

        got_request_exception.connect(record, app)
        try:
            api.handle_error(exception)
            assert len(recorded) == 0
        finally:
            got_request_exception.disconnect(record, app)

    def test_handle_error(self, app):
        api = restx.Api(app)

        response = api.handle_error(BadRequest())
        assert response.status_code == 400
        assert json.loads(response.data.decode()) == {
            "message": BadRequest.description,
        }

    def test_handle_error_does_not_duplicate_content_length(self, app):
        api = restx.Api(app)

        # with self.app.test_request_context("/foo"):
        response = api.handle_error(BadRequest())
        assert len(response.headers.getlist("Content-Length")) == 1

    def test_handle_smart_errors(self, app):
        api = restx.Api(app)
        view = restx.Resource

        api.add_resource(view, "/foo", endpoint="bor")
        api.add_resource(view, "/fee", endpoint="bir")
        api.add_resource(view, "/fii", endpoint="ber")

        with app.test_request_context("/faaaaa"):
            response = api.handle_error(NotFound())
            assert response.status_code == 404
            assert json.loads(response.data.decode()) == {
                "message": NotFound.description,
            }

        with app.test_request_context("/fOo"):
            response = api.handle_error(NotFound())
            assert response.status_code == 404
            assert "did you mean /foo ?" in response.data.decode()

        app.config["RESTX_ERROR_404_HELP"] = False

        response = api.handle_error(NotFound())
        assert response.status_code == 404
        assert json.loads(response.data.decode()) == {"message": NotFound.description}

    def test_handle_include_error_message(self, app):
        api = restx.Api(app)
        view = restx.Resource

        api.add_resource(view, "/foo", endpoint="bor")

        with app.test_request_context("/faaaaa"):
            response = api.handle_error(NotFound())
            assert "message" in json.loads(response.data.decode())

    def test_handle_not_include_error_message(self, app):
        app.config["ERROR_INCLUDE_MESSAGE"] = False

        api = restx.Api(app)
        view = restx.Resource

        api.add_resource(view, "/foo", endpoint="bor")

        with app.test_request_context("/faaaaa"):
            response = api.handle_error(NotFound())
            assert "message" not in json.loads(response.data.decode())

    def test_error_router_falls_back_to_original(self, app, mocker):
        class ProgrammingBlunder(Exception):
            pass

        blunder = ProgrammingBlunder("This exception needs to be detectable")

        def raise_blunder(arg):
            raise blunder

        api = restx.Api(app)
        app.handle_exception = mocker.Mock()
        api.handle_error = mocker.Mock(side_effect=raise_blunder)
        api._has_fr_route = mocker.Mock(return_value=True)
        exception = mocker.Mock(spec=HTTPException)

        api.error_router(app.handle_exception, exception)

        app.handle_exception.assert_called_with(blunder)

    def test_fr_405(self, app, client):
        api = restx.Api(app)

        @api.route("/ids/<int:id>", endpoint="hello")
        class HelloWorld(restx.Resource):
            def get(self):
                return {}

        response = client.post("/ids/3")
        assert response.status_code == 405
        assert response.content_type == api.default_mediatype
        # Allow can be of the form 'GET, PUT, POST'
        allow = ", ".join(set(response.headers.get_all("Allow")))
        allow = set(method.strip() for method in allow.split(","))
        assert allow == set(["HEAD", "OPTIONS", "GET"])

    @pytest.mark.options(debug=True)
    def test_exception_header_forwarded(self, app, client):
        """Ensure that HTTPException's headers are extended properly"""
        api = restx.Api(app)

        class NotModified(HTTPException):
            code = 304

            def __init__(self, etag, *args, **kwargs):
                super(NotModified, self).__init__(*args, **kwargs)
                self.etag = quote_etag(etag)

            def get_headers(self, *args, **kwargs):
                return [("ETag", self.etag)]

        custom_abort = Aborter(mapping={304: NotModified})

        @api.route("/foo")
        class Foo1(restx.Resource):
            def get(self):
                custom_abort(304, etag="myETag")

        foo = client.get("/foo")
        assert foo.get_etag() == unquote_etag(quote_etag("myETag"))

    def test_handle_server_error(self, app):
        api = restx.Api(app)

        resp = api.handle_error(Exception())
        assert resp.status_code == 500
        assert json.loads(resp.data.decode()) == {"message": "Internal Server Error"}

    def test_handle_error_with_code(self, app):
        api = restx.Api(app, serve_challenge_on_401=True)

        exception = Exception()
        exception.code = "Not an integer"
        exception.data = {"foo": "bar"}

        response = api.handle_error(exception)
        assert response.status_code == 500
        assert json.loads(response.data.decode()) == {"foo": "bar"}

    def test_errorhandler_swagger_doc(self, app, client):
        api = restx.Api(app)

        class CustomException(RuntimeError):
            pass

        error = api.model("Error", {"message": restx.fields.String()})

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                """
                Do something

                :raises CustomException: In case of something
                """
                pass

        @api.errorhandler(CustomException)
        @api.header("Custom-Header", "Some custom header")
        @api.marshal_with(error, code=503)
        def handle_custom_exception(error):
            """Some description"""
            pass

        specs = client.get_specs()

        assert "Error" in specs["definitions"]
        assert "CustomException" in specs["responses"]

        response = specs["responses"]["CustomException"]
        assert response["description"] == "Some description"
        assert response["schema"] == {"$ref": "#/definitions/Error"}
        assert response["headers"] == {
            "Custom-Header": {"description": "Some custom header", "type": "string"}
        }

        operation = specs["paths"]["/test/"]["get"]
        assert "responses" in operation
        assert operation["responses"] == {
            "503": {"$ref": "#/responses/CustomException"}
        }

    def test_errorhandler_with_propagate_true(self, app, client):
        """Exceptions with errorhandler should not be returned to client, even
        if PROPAGATE_EXCEPTIONS is set."""
        app.config["PROPAGATE_EXCEPTIONS"] = True
        api = restx.Api(app)

        @api.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise RuntimeError("error")

        @api.errorhandler(RuntimeError)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        response = client.get("/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }

    def test_namespace_errorhandler_with_propagate_true(self, app, client):
        """Exceptions with errorhandler on a namespace should not be
        returned to client, even if PROPAGATE_EXCEPTIONS is set."""
        app.config["PROPAGATE_EXCEPTIONS"] = True
        api = restx.Api(app)
        namespace = restx.Namespace("test_namespace")
        api.add_namespace(namespace)

        @namespace.route("/test/", endpoint="test")
        class TestResource(restx.Resource):
            def get(self):
                raise RuntimeError("error")

        @namespace.errorhandler(RuntimeError)
        def handle_custom_exception(error):
            return {"message": str(error), "test": "value"}, 400

        response = client.get("/test_namespace/test/")
        assert response.status_code == 400
        assert response.content_type == "application/json"

        data = json.loads(response.data.decode("utf8"))
        assert data == {
            "message": "error",
            "test": "value",
        }
